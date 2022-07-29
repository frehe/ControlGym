import numpy as np
import tensorflow as tf

from typing import Optional, Union, Tuple
from CartPoleSimulation.CartPole import CartPole
from CartPoleSimulation.CartPole.cartpole_model import Q2u
from CartPoleSimulation.CartPole.cartpole_model_tf import _cartpole_ode, cartpole_integration_tf
from CartPoleSimulation.CartPole.cartpole_tf import _cartpole_fine_integration_tf
from CartPoleSimulation.CartPole.state_utilities import (
    ANGLE_COS_IDX,
)

from Environments import EnvironmentBatched, NumpyLibrary, TensorType, cost_functions

from CartPoleSimulation.GymlikeCartPole.CartPoleEnv_LTC import CartPoleEnv_LTC

from gym.spaces import Box
from gym.utils.renderer import Renderer

class cartpole_simulator_batched(EnvironmentBatched, CartPoleEnv_LTC):
    num_actions = 1
    num_states = 6

    def __init__(
        self, batch_size=1, computation_lib=NumpyLibrary, render_mode="human", **kwargs
    ):
        self.config = kwargs

        self._batch_size = batch_size
        self._actuator_noise = np.array(kwargs["actuator_noise"], dtype=np.float32)
        self.render_mode = render_mode
        self.renderer = Renderer(self.render_mode, super().render)

        self.set_computation_library(computation_lib)
        self._set_up_rng(kwargs["seed"])
        self.cost_functions = cost_functions(self)
        self.dt = self.lib.to_tensor(kwargs["dt"], self.lib.float32)

        self.CartPoleInstance = CartPole()
        self.CartPoleInstance.dt_simulation = self.dt
        self.mode = kwargs["mode"]

        if self.mode != "stabilization":
            raise NotImplementedError("Only stabilization mode defined for now.")

        self.min_action = -1.0
        self.max_action = 1.0

        cart_length = kwargs["cart_length"]
        usable_track_length = kwargs["usable_track_length"]
        track_half_length = (usable_track_length - cart_length) / 2.0
        self.u_max = kwargs["u_max"]

        self.x_threshold = (
            0.9 * track_half_length
        )  # Takes care that the cart is not going beyond the boundary

        observation_space_boundary = np.array(
            [
                np.float32(np.pi),
                np.finfo(np.float32).max,
                1.0,
                1.0,
                np.float32(track_half_length),
                np.finfo(np.float32).max,
            ]
        )

        self.observation_space = Box(
            -observation_space_boundary, observation_space_boundary
        )
        self.action_space = Box(
            low=np.float32(self.min_action),
            high=np.float32(self.max_action),
            shape=(1,),
        )

        self.viewer = None
        self.screen = None
        self.isopen = False
        self.state = None
        self.action = None
        self.reward = None
        self.target = None
        self.done = False

        self.steps_beyond_done = None

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
            high = np.array([self.lib.pi / 2, 1.0e-1, 5.0e-1, 1.0e-1])
            angle, angleD, position, positionD = self.lib.unstack(
                self.lib.uniform(
                    self.rng, [self._batch_size, 4], -high, high, self.lib.float32
                ),
                4,
                1,
            )
            self.state = self.lib.stack(
                [
                    angle,
                    angleD,
                    self.lib.cos(angle),
                    self.lib.sin(angle),
                    position,
                    positionD,
                ],
                1,
            )
            self.target = self.lib.to_tensor(
                self.CartPoleInstance.target_position, self.lib.float32
            )
            self.steps_beyond_done = None
        else:
            self.state = state

        if self._batch_size == 1:
            self.state = self.lib.to_numpy(self.lib.squeeze(self.state))

        if return_info:
            return tuple((self.state, {}))
        return self.state

    def step_tf(self, state: tf.Tensor, action: tf.Tensor):
        state, action = self._expand_arrays(state, action)

        # Perturb action if not in planning mode
        if self._batch_size == 1:
            action += self._generate_actuator_noise()

        state_updated = self.step_physics(state, action)

        return state_updated

    def step(self, action: tf.Tensor):
        self.state, action = self._expand_arrays(self.state, action)

        # Perturb action if not in planning mode
        if self._batch_size == 1:
            action += self._generate_actuator_noise()

        self.state = self.step_physics(self.state, action)

        # Update the total time of the simulation
        self.CartPoleInstance.step_time()
        self.CartPoleInstance.target_position = (
            0.0  # TODO: Make option of random target position
        )

        reward = self.get_reward(self.state, action)
        done = self.is_done(self.state)

        if self._batch_size == 1:
            self.state = self.lib.to_numpy(self.lib.squeeze(self.state))
            reward = float(reward)

        return (
            self.state,
            reward,
            done,
            {"target": self.CartPoleInstance.target_position},
        )

    def step_physics(self, state: TensorType, action: TensorType):
        # Convert dimensionless motor power to a physical force acting on the Cart
        u = self.u_max * (action[:, 0])

        angle, angleD, angle_cos, angle_sin, position, positionD = self.lib.unstack(state, 6, 1)

        # Compute next state
        angleDD, positionDD = _cartpole_ode(angle_cos, angle_sin, angleD, positionD, u)

        angle, angleD, position, positionD = cartpole_integration_tf(angle, angleD, angleDD, position, positionD, positionDD, self.dt)
        angle_cos = self.lib.cos(angle)
        angle_sin = self.lib.sin(angle)

        angle = self.lib.atan2(angle_sin, angle_cos)

        next_state = self.lib.stack(
            [angle, angleD, angle_cos, angle_sin, position, positionD], 1
        )

        return next_state

    def get_reward(self, state, action):
        reward = -state[..., ANGLE_COS_IDX]
        return reward

    def is_done(self, state):
        return False
    
    def render(self, mode="human"):
        if self.render_mode is not None:
            return self.renderer.get_renders()
        else:
            return super().render(mode)
