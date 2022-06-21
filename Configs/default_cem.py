from Environments.continuous_mountain_car_batched import Continuous_MountainCarEnv_Batched

ENV_NAME = "MountainCarContinuous-v0"
ENV = Continuous_MountainCarEnv_Batched
NUM_ITERATIONS = 300

CONTROLLER_NAME = "ControllerCem"

CONTROLLER_CONFIG = {
    "SEED": 12345,
    "mpc_horizon": 2,
    "dt": 0.02,
    "cem_outer_it": 5,
    "cem_rollouts": 100,
    "cem_predictor_type": "EulerTF",
    "cem_stdev_min": 0.1,
    "cem_R": 1,
    "cem_ccrc_weight": 1,
    "cem_best_k": 5,
    "cem_LR": 0.1,
    "cem_initial_action_variance": 0.5
}