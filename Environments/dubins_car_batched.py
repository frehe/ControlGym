# Original Source: https://github.com/gargivaidya/dubin_model_gymenv/blob/main/dubin_gymenv.py

from typing import Optional, Union, Tuple
import numpy as np
import matplotlib.pyplot as plt
import math
import gym
from gym import spaces
import time
import itertools
import datetime
import tensorflow as tf

from Environments import EnvironmentBatched, NumpyLibrary, cost_functions

# Training constants
MAX_STEER = np.pi / 4
MAX_SPEED = 10.0
MIN_SPEED = 0.0
THRESHOLD_DISTANCE_2_GOAL = 0.05
MAX_X = 10.0
MAX_Y = 10.0
max_ep_length = 800

# Vehicle parameters
LENGTH = 0.45  # [m]
WIDTH = 0.2  # [m]
BACKTOWHEEL = 0.1  # [m]
WHEEL_LEN = 0.03  # [m]
WHEEL_WIDTH = 0.02  # [m]
TREAD = 0.07  # [m]
WB = 0.25  # [m]

show_animation = True


class dubins_car_batched(EnvironmentBatched, gym.Env):
    num_states = 3
    num_actions = 2
    metadata = {"render_modes": ["console", "single_rgb_array", "rgb_array", "human"]}

    def __init__(
        self,
        waypoints,
        target_point,
        n_waypoints,
        batch_size=1,
        computation_lib=NumpyLibrary,
        render_mode: str = None,
        **kwargs
    ):
        super(dubins_car_batched, self).__init__()

        self.set_computation_library(computation_lib)
        self._set_up_rng(kwargs["seed"])
        self.cost_functions = cost_functions(self)

        self._batch_size = batch_size
        self._actuator_noise = np.array(kwargs["actuator_noise"], dtype=np.float32)
        self.render_mode = render_mode

        self.action_space = spaces.Box(
            np.array([MIN_SPEED, -MAX_STEER]),
            np.array([MAX_SPEED, MAX_STEER]),
            dtype=np.float32,
        )  # Action space for [throttle, steer]
        low = np.array([-1.0, -1.0, -4.0])  # low range of observation space
        high = np.array([1.0, 1.0, 4.0])  # high range of observation space
        self.observation_space = spaces.Box(
            low, high, dtype=np.float32
        )  # Observation space for [x, y, theta]

        # if target_point is None:
        #     self.target = self.lib.to_numpy(self.lib.uniform(self.rng, (3,), [-1.0, -1.0, -np.pi/2], [1.0, 1.0, np.pi/2], self.lib.float32))
        # else:
        self.target = target_point

        self.action = [0.0, 0.0]  # Action

        self.config = {
            **kwargs,
            **dict(
                waypoints=waypoints,
                target_point=self.target,
                n_waypoints=n_waypoints,
            ),
        }

        self.fig: plt.Figure = None
        self.ax: plt.Axes = None

    def reset(
        self,
        state: np.ndarray = None,
        seed: Optional[int] = None,
        return_info: bool = False,
        options: Optional[dict] = None,
    ) -> Tuple[np.ndarray, Optional[dict]]:
        if seed is not None:
            self._set_up_rng(seed)

        if state is None:
            x = self.rng.uniform(-1.0, 1.0, (1, 1))
            y = self.rng.choice([-1.0, 1.0], (1, 1)) * self.lib.sqrt(1.0 - x**2)
            theta = self.get_heading(
                self.lib.concat([x, y], 1), self.lib.unsqueeze(self.target, 0)
            )
            yaw = self.rng.uniform(theta - MAX_STEER, theta + MAX_STEER, (1, 1))

            self.state = self.lib.stack([x, y, yaw], 1)
            self.traj_x = [float(x * MAX_X)]
            self.traj_y = [float(y * MAX_Y)]
            self.traj_yaw = [float(yaw)]
            if self._batch_size > 1:
                self.state = np.tile(self.state, (self._batch_size, 1))
        else:
            if self.lib.ndim(state) < 2:
                state = self.lib.unsqueeze(
                    self.lib.to_tensor(state, self.lib.float32), 0
                )
            if self.lib.shape(state)[0] == 1:
                self.state = self.lib.tile(state, (self._batch_size, 1))
            else:
                self.state = state

        return self._get_reset_return_val()

    def get_reward(self, state, action):
        state, action = self._expand_arrays(state, action)
        x, y, yaw_car = self.lib.unstack(state, 3, 1)
        x_target, y_target, yaw_target = self.target

        head_to_target = self.get_heading(state, self.lib.unsqueeze(self.target, 0))
        alpha = head_to_target - yaw_car
        ld = self.get_distance(state, self.lib.unsqueeze(self.target, 0))
        crossTrackError = self.lib.sin(alpha) * ld

        car_in_bounds = (self.lib.abs(x) < 1.0) & (self.lib.abs(y) < 1.0)
        car_at_target = (
            (self.lib.abs(x - x_target) < THRESHOLD_DISTANCE_2_GOAL)
            & (self.lib.abs(y - y_target) < THRESHOLD_DISTANCE_2_GOAL)
            & (self.lib.abs(yaw_car - yaw_target) < 0.1)
        )

        reward = (
            self.lib.cast(car_in_bounds & car_at_target, self.lib.float32) * 10.0
            + self.lib.cast(car_in_bounds & (~car_at_target), self.lib.float32)
            * (
                -1.0
                * (
                    3 * self.lib.abs(crossTrackError)
                    + self.lib.abs(x - x_target)
                    + self.lib.abs(y - y_target)
                    + 3 * self.lib.abs(head_to_target - yaw_car) / MAX_STEER
                )
                / 8.0
            )
            + self.lib.cast(~car_in_bounds, self.lib.float32) * (-1.0)
        )

        return reward

    def is_done(self, state):
        x, y, yaw_car = self.lib.unstack(state, 3, 1)
        x_target = self.target[0]
        y_target = self.target[1]

        car_in_bounds = (self.lib.abs(x) < 1.0) & (self.lib.abs(y) < 1.0)
        car_at_target = (self.lib.abs(x - x_target) < THRESHOLD_DISTANCE_2_GOAL) & (
            self.lib.abs(y - y_target) < THRESHOLD_DISTANCE_2_GOAL
        )
        done = ~(car_in_bounds & (~car_at_target))
        return done

    def get_distance(self, x1, x2):
        # Distance between points x1 and x2
        return self.lib.sqrt((x1[:, 0] - x2[:, 0]) ** 2 + (x1[:, 1] - x2[:, 1]) ** 2)

    def get_heading(self, x1, x2):
        # Heading between points x1,x2 with +X axis
        return self.lib.atan2((x2[:, 1] - x1[:, 1]), (x2[:, 0] - x1[:, 0]))

    def step_tf(self, state: tf.Tensor, action: tf.Tensor):
        state, action = self._expand_arrays(state, action)

        # Perturb action if not in planning mode
        if self._batch_size == 1:
            action += self._generate_actuator_noise()

        state = self.update_state(state, action, 0.005)

        return state

    def step(
        self, action: Union[np.ndarray, tf.Tensor]
    ) -> Tuple[
        Union[np.ndarray, tf.Tensor],
        Union[np.ndarray, float],
        Union[np.ndarray, bool],
        dict,
    ]:
        self.state, action = self._expand_arrays(self.state, action)

        # Perturb action if not in planning mode
        if self._batch_size == 1:
            action += self._generate_actuator_noise()

        info = {}

        self.state = self.update_state(self.state, action, 0.005)

        done = self.is_done(self.state)
        reward = self.get_reward(self.state, action)

        self.state = self.lib.squeeze(self.state)

        if self._batch_size == 1:
            return self.lib.to_numpy(self.state), float(reward), bool(done), {}

        return self.state, reward, done, {}

    def render(self):
        if self.render_mode in {"rgb_array", "single_rgb_array"}:
            # Turn interactive plotting off
            plt.ioff()

        # Storing tracked trajectory
        self.traj_x.append(self.state[0] * MAX_X)
        self.traj_y.append(self.state[1] * MAX_Y)
        self.traj_yaw.append(self.state[2])

        # for stopping simulation with the esc key.
        if self.fig is None:
            self.fig, self.ax = plt.subplots(nrows=1, ncols=1, figsize=(6, 6))
        self.ax.cla()
        self.fig.canvas.mpl_connect(
            "key_release_event",
            lambda event: [exit(0) if event.key == "escape" else None],
        )
        # self.ax: plt.Axes = self.fig.axes[0]
        self.ax.plot(self.traj_x, self.traj_y, "ob", markersize=2, label="trajectory")
        # # Rendering waypoint sequence
        # for i in range(len(self.waypoints)):
        #     self.ax.plot(
        #         self.waypoints[i][0] * MAX_X,
        #         self.waypoints[i][1] * MAX_Y,
        #         "^r",
        #         label="waypoint",
        #     )
        self.ax.plot(
            self.target[0] * MAX_X, self.target[1] * MAX_Y, "xg", label="target"
        )
        # Rendering the car and action taken
        self.plot_car()
        self.ax.set_aspect("equal", adjustable="datalim")
        self.ax.grid(True)
        # self.ax.set_title("Simulation")
        plt.pause(0.0001)

        if self.render_mode in {"rgb_array", "single_rgb_array"}:
            data = np.frombuffer(self.fig.canvas.tostring_rgb(), dtype=np.uint8)
            data = data.reshape(
                tuple(
                    (self.fig.get_size_inches() * self.fig.dpi).astype(np.int32)[::-1]
                )
                + (3,)
            )
            return data

    def close(self):
        # For Gym AI compatibility
        pass

    def update_state(self, state, action, DT):
        x, y, yaw_car = self.lib.unstack(state, 3, 1)
        throttle, steer = self.lib.unstack(action, 2, 1)
        # Update the pose as per Dubin's equations

        steer = self.lib.clip(steer, -MAX_STEER, MAX_STEER)
        throttle = self.lib.clip(throttle, MIN_SPEED, MAX_SPEED)

        x = x + throttle * self.lib.cos(yaw_car) * DT
        y = y + throttle * self.lib.sin(yaw_car) * DT
        yaw_car = yaw_car + throttle / WB * self.lib.tan(steer) * DT
        return self.lib.stack([x, y, yaw_car], 1)

    def plot_car(self, cabcolor="-r", truckcolor="-k"):  # pragma: no cover
        # print("Plotting Car")
        # Scale up the car pose to MAX_X, MAX_Y grid
        x = self.state[0] * MAX_X
        y = self.state[1] * MAX_Y
        yaw = self.state[2]
        steer = self.action[1] * MAX_STEER

        outline = np.array(
            [
                [
                    -BACKTOWHEEL,
                    (LENGTH - BACKTOWHEEL),
                    (LENGTH - BACKTOWHEEL),
                    -BACKTOWHEEL,
                    -BACKTOWHEEL,
                ],
                [WIDTH / 2, WIDTH / 2, -WIDTH / 2, -WIDTH / 2, WIDTH / 2],
            ]
        )

        fr_wheel = np.array(
            [
                [WHEEL_LEN, -WHEEL_LEN, -WHEEL_LEN, WHEEL_LEN, WHEEL_LEN],
                [
                    -WHEEL_WIDTH - TREAD,
                    -WHEEL_WIDTH - TREAD,
                    WHEEL_WIDTH - TREAD,
                    WHEEL_WIDTH - TREAD,
                    -WHEEL_WIDTH - TREAD,
                ],
            ]
        )

        rr_wheel = np.copy(fr_wheel)

        fl_wheel = np.copy(fr_wheel)
        fl_wheel[1, :] *= -1
        rl_wheel = np.copy(rr_wheel)
        rl_wheel[1, :] *= -1

        Rot1 = np.array(
            [[math.cos(yaw), math.sin(yaw)], [-math.sin(yaw), math.cos(yaw)]]
        )
        Rot2 = np.array(
            [[math.cos(steer), math.sin(steer)], [-math.sin(steer), math.cos(steer)]]
        )

        fr_wheel = (fr_wheel.T.dot(Rot2)).T
        fl_wheel = (fl_wheel.T.dot(Rot2)).T
        fr_wheel[0, :] += WB
        fl_wheel[0, :] += WB

        fr_wheel = (fr_wheel.T.dot(Rot1)).T
        fl_wheel = (fl_wheel.T.dot(Rot1)).T

        outline = (outline.T.dot(Rot1)).T
        rr_wheel = (rr_wheel.T.dot(Rot1)).T
        rl_wheel = (rl_wheel.T.dot(Rot1)).T

        outline[0, :] += x
        outline[1, :] += y
        fr_wheel[0, :] += x
        fr_wheel[1, :] += y
        rr_wheel[0, :] += x
        rr_wheel[1, :] += y
        fl_wheel[0, :] += x
        fl_wheel[1, :] += y
        rl_wheel[0, :] += x
        rl_wheel[1, :] += y

        self.ax.plot(
            np.array(outline[0, :]).flatten(),
            np.array(outline[1, :]).flatten(),
            truckcolor,
        )
        self.ax.plot(
            np.array(fr_wheel[0, :]).flatten(),
            np.array(fr_wheel[1, :]).flatten(),
            truckcolor,
        )
        self.ax.plot(
            np.array(rr_wheel[0, :]).flatten(),
            np.array(rr_wheel[1, :]).flatten(),
            truckcolor,
        )
        self.ax.plot(
            np.array(fl_wheel[0, :]).flatten(),
            np.array(fl_wheel[1, :]).flatten(),
            truckcolor,
        )
        self.ax.plot(
            np.array(rl_wheel[0, :]).flatten(),
            np.array(rl_wheel[1, :]).flatten(),
            truckcolor,
        )
        self.ax.plot(x, y, "*")
