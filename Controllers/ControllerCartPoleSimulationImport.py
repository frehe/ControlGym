from importlib import import_module
import numpy as np
import torch
from Environments import EnvironmentBatched, PyTorchLibrary

from Controllers import Controller


class ControllerCartPoleSimulationImport(Controller):
    def __init__(self, environment: EnvironmentBatched, **controller_config) -> None:
        super().__init__(environment, **controller_config)
        controller_name = controller_config["controller"]

        controller_full_name = f"controller_{controller_name.replace('-', '_')}"
        self._controller = getattr(
            import_module(
                f"CartPoleSimulation.Controllers.{controller_full_name}"
            ),
            controller_full_name,
        )(**controller_config[controller_name])

    def step(self, s: np.ndarray) -> np.ndarray:
        # self._predictor_environment.reset(s)

        self.u = self._controller.step(s)
        self.Q = self._controller.Q.copy()
        self.J = self._controller.J.copy()

        # Q: (batch_size x horizon_length x action_space)
        # J: (batch_size)
        self.s = s.copy()
        self._update_logs()
        return self.u
