from typing import Optional
import numpy as np
import tensorflow as tf

from gym import spaces
from gym.utils import seeding

from gym.envs.classic_control.pendulum import PendulumEnv, angle_normalize


_PI = tf.constant(np.pi, dtype=tf.float32)


class PendulumEnv_Batched(PendulumEnv):
    def __init__(self, g=10, batch_size=1):
        super().__init__(g)
        self._batch_size = batch_size

        high = np.array([np.pi, self.max_speed], dtype=np.float32)
        self.observation_space = spaces.Box(low=-high, high=high, dtype=np.float32)

    def _angle_normalize(self, x):
        return ((x + _PI) % (2 * _PI)) - _PI

    def step(self, action: np.ndarray):
        if action.ndim < 2:
            action = tf.reshape(
                action, [self._batch_size, sum(self.action_space.shape)]
            )
        if self.state.ndim < 2:
            self.state = tf.reshape(
                self.state, [self._batch_size, sum(self.observation_space.shape)]
            )

        th, thdot = tf.unstack(self.state, axis=1)  # th := theta

        g = self.g
        m = self.m
        l = self.l
        dt = self.dt

        action = tf.clip_by_value(action, -self.max_torque, self.max_torque)[:, 0]
        self.last_action = action  # for rendering
        costs = (
            self._angle_normalize(th) ** 2 + 0.1 * thdot**2 + 0.001 * (action**2)
        )

        newthdot = (
            thdot + (3 * g / (2 * l) * tf.sin(th) + 3.0 / (m * l**2) * action) * dt
        )
        newthdot = tf.clip_by_value(newthdot, -self.max_speed, self.max_speed)
        newth = th + newthdot * dt

        self.state = tf.squeeze(tf.stack([newth, newthdot], axis=1))

        if self._batch_size == 1:
            return tf.squeeze(self.state).numpy(), -float(costs), False, {}

        return self.state, -costs, False, {}

    def reset(
        self,
        state: np.ndarray = None,
        seed: Optional[int] = None,
        return_info: bool = False,
        options: Optional[dict] = None,
    ):
        if seed is not None:
            self._np_random, seed = seeding.np_random(seed)

        if state is None:
            if self._batch_size == 1:
                high = np.array([np.pi, 1])
            else:
                high = np.tile(np.array([np.pi, 1]), (self._batch_size, 1))
            self.state = tf.convert_to_tensor(
                self.np_random.uniform(low=-high, high=high), dtype=tf.float32
            )
        else:
            if state.ndim < 2:
                state = tf.expand_dims(state, axis=0)
            self.state = tf.tile(state, (self._batch_size, 1))

        self.last_u = None

        if self._batch_size == 1:
            self.state = tf.squeeze(self.state).numpy()

        if not return_info:
            return self.state
        else:
            return self.state, {}

    # def render(self, mode="human"):
    #     if self._batch_size == 1:
    #         return super().render(mode)
    #     else:
    #         raise NotImplementedError("Rendering not implemented for batched mode")
