from typing import Optional, Tuple, Union

import numpy as np
from numpy.random import Generator, SFC64
import tensorflow as tf
from gym.envs.registration import register

ENV_REGISTRY = {
    "CustomEnvironments/CartPoleContinuous": "Environments.continuous_cartpole_batched:Continuous_CartPoleEnv_Batched",
    "CustomEnvironments/MountainCarContinuous": "Environments.continuous_mountaincar_batched:Continuous_MountainCarEnv_Batched",
    "CustomEnvironments/Pendulum": "Environments.pendulum_batched:PendulumEnv_Batched",
}

for identifier, entry_point in ENV_REGISTRY.items():
    register(
        id=identifier,
        entry_point=entry_point,
        max_episode_steps=None,
    )


class EnvironmentBatched:
    def step(
        self, action: Union[np.ndarray, tf.Tensor]
    ) -> Tuple[
        Union[np.ndarray, tf.Tensor],
        Union[np.ndarray, float],
        Union[np.ndarray, bool],
        dict,
    ]:
        return NotImplementedError()

    def reset(
        self,
        state: np.ndarray = None,
        seed: Optional[int] = None,
        return_info: bool = False,
        options: Optional[dict] = None,
    ) -> Tuple[np.ndarray, Optional[dict]]:
        return NotImplementedError()
    
    def _set_up_rng(self, seed: int = None, actuator_noise: list[float] = None) -> None:
        self._actuator_noise = actuator_noise
        self._rng_np = Generator(SFC64(seed=0 if seed is None else seed))

    def _generate_actuator_noise(self):
        return (
            self._actuator_noise
            * (self.action_space.high - self.action_space.low)
            * self._rng_np.standard_normal((self._batch_size, len(self._actuator_noise)), dtype=np.float32)
        )

    def _expand_arrays(
        self, state: Union[np.ndarray, tf.Tensor], action: Union[np.ndarray, tf.Tensor]
    ):
        if action.ndim < 2:
            action = tf.reshape(
                action, [self._batch_size, sum(self.action_space.shape)]
            )
        if state.ndim < 2:
            state = tf.reshape(
                state, [self._batch_size, sum(self.observation_space.shape)]
            )
        return state, action

    def _get_reset_return_val(self, return_info: bool = False):
        if self._batch_size == 1:
            self.state = tf.squeeze(self.state).numpy()

        ret_val = (
            self.state.numpy() if isinstance(self.state, tf.Tensor) else self.state
        )
        if return_info:
            ret_val = tuple((ret_val, {}))
        return ret_val
