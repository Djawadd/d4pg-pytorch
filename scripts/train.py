from datetime import datetime
import random
from multiprocessing import set_start_method
import torch.multiprocessing as torch_mp
try:
    set_start_method('spawn')
except RuntimeError:
    pass
import os
from shutil import copyfile

from models.utils import create_learner
from models.agent import Agent
from utils.utils import read_config
from utils.reward_plot import plot_rewards
from utils.logger import Logger


def sampler_worker(config, replay_queue, batch_queue, stop_agent_event,
                   global_episode, log_dir=''):
    """
    Function that transfers replay to the buffer and batches from buffer to the queue.

    Args:
        config:
        replay_queue:
        batch_queue:
        stop_agent_event:
        global_episode:
        log_dir:

    Returns:

    """
    num_agents = config['num_agents']
    batch_size = config['batch_size']

    # Logger
    fn = f"{log_dir}/data_struct.pkl"
    logger = Logger(log_path=fn)

    # TODO: Replace with data structure
    replay_buffer = []

    while not stop_agent_event.value or not replay_queue.empty():
        # (1) Transfer replays to global buffer
        for _ in range(num_agents):
            if replay_queue.empty():
                break
            replay = replay_queue.get()
            replay_buffer.append(replay)

        # (2) Transfer batch of replay from buffer to the batch_queue
        if len(replay_buffer) < batch_size:
            continue
        idxes = [random.randint(0, len(replay_buffer) - 1) for _ in range(batch_size)]
        elems = [replay_buffer[i] for i in idxes]
        batch_queue.put(elems)

        # Log data structures sizes
        logger.scalar_summary("global_episode", global_episode.value)
        logger.scalar_summary("replay_queue", replay_queue.qsize())
        logger.scalar_summary("batch_queue", batch_queue.qsize())

    print("Stop sampler worker.")


def train(config_path, config=None):

    # Config
    if config is None:
        config = read_config(config_path)
    replay_queue_size = config['replay_queue_size']
    batch_queue_size = config['batch_queue_size']
    n_agents = config['num_agents']

    # Create directory for experiment
    experiment_dir = f"{config['results_path']}/{datetime.now():%Y-%m-%d_%H:%M:%S}"
    if not os.path.exists(experiment_dir):
        os.makedirs(experiment_dir)
    copyfile(config_path, f"{experiment_dir}/config.yml")

    # Data structures
    processes = []
    replay_queue = torch_mp.Queue(maxsize=replay_queue_size)
    stop_agent_event = torch_mp.Value('i', 0)
    global_episode = torch_mp.Value('i', 0)

    # Data sampler
    batch_queue = torch_mp.Queue(maxsize=batch_queue_size)
    p = torch_mp.Process(target=sampler_worker,
                         args=(config, replay_queue, batch_queue, stop_agent_event,
                               global_episode, experiment_dir))
    processes.append(p)

    # Learner (neural net training process)
    learner = create_learner(config, batch_queue, log_dir=experiment_dir)
    p = torch_mp.Process(target=learner.run, args=(stop_agent_event,))
    processes.append(p)

    # Agents (exploration processes)
    for i in range(n_agents):
        agent = Agent(config,
                      actor_learner=learner.target_policy_net,
                      global_episode=global_episode,
                      n_agent=i,
                      log_dir=experiment_dir)
        p = torch_mp.Process(target=agent.run, args=(replay_queue, stop_agent_event))
        processes.append(p)

    for p in processes:
        p.start()
    for p in processes:
        p.join()

    # Plot reward from all agents
    plot_rewards(experiment_dir)

    print("End.")


if __name__ == "__main__":
    CONFIG_PATH = "config.yml"
    train(CONFIG_PATH)
