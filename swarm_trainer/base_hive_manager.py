import os
import sys
import psutil
from rlbot.botmanager.bot_helper_process import BotHelperProcess
from rlbot.utils.logging_utils import get_logger
import time

from framework.utils import get_repo_directory


class BaseHiveManager(BotHelperProcess):

    batch_size = 500
    memory_size = 100000

    def __init__(self, agent_metadata_queue, quit_event, options):
        super().__init__(agent_metadata_queue, quit_event, options)
        sys.path.insert(0, get_repo_directory())  # this is for separate process imports
        self.logger = get_logger('base_hive_mgr')

        self.actor_model = self.get_model()
        self.shared_model_handle = self.get_shared_model_handle()
        self.manager = self.setup_manager()

        action_shape = self.actor_model.get_model_output_dimension()[0]
        state_shape_list = self.actor_model.get_input_state_dimension()

        shape_dict = {
            'spatial': state_shape_list[0],
            'extra': state_shape_list[1],
            'action': action_shape,
            'mask': action_shape,
            'teacher_action': action_shape,
            'time': (),
        }
        print(shape_dict)

        self.game_memory = self.manager.Memory(self.memory_size, shape_dict)
        self.model_path = None
        self.load_model = None

        self.setup_trainer()

    def get_model(self):
        raise NotImplementedError()

    def get_shared_model_handle(self):
        raise NotImplementedError()

    @staticmethod
    def setup_manager():
        from multiprocessing.managers import BaseManager
        from swarm_trainer.memory import BaseMemory

        BaseManager.register('Memory', BaseMemory)
        manager = BaseManager()
        manager.start()

        return manager

    def setup_trainer(self):
        raise NotImplementedError()

    def start(self):
        while not self.metadata_queue.empty():
            metadata = self.metadata_queue.get()
            pipe = metadata.helper_process_request.pipe
            self.model_path = metadata.helper_process_request.model_path
            self.load_model = metadata.helper_process_request.load_model

            pipe.send(self.shared_model_handle)
            pipe.send(self.game_memory)

        self.logger.info('set up all agents')

        my_process = psutil.Process()
        my_process.cpu_affinity([0, 2])
        my_process.nice(psutil.NORMAL_PRIORITY_CLASS)

        self.game_loop()

    def game_loop(self):
        """
        Loops through the game providing training as data is collected.
        :return:
        """
        self.initialize_training(load_model=self.load_model)

        while not self.quit_event.is_set():
            self.learn_memory()

        self.finish_training()

    def learn_memory(self):
        if self.game_memory.get_size() >= 20000:
            data_dict = self.game_memory.get_sample(self.batch_size)
            self.train_step(data_dict)
        else:
            time.sleep(5)
            print(self.game_memory.get_size())

    def initialize_training(self, load_model=False, load_exp=False):
        raise NotImplementedError()

    def train_step(self, data_list):
        """
        Performs a single train step on the data given.
        All data (input, output, rewards) should end up producing arrays of the same length
        :param data_list contains the data that was saved by the agents
        :return:
        """
        raise NotImplementedError()

    def finish_training(self, save_model=True, save_exp=False):
        raise NotImplementedError()

    def get_model_name(self):
        return str(type(self.actor_model).__name__)

    def get_file_path(self):
        return os.path.join(get_repo_directory(), self.model_path)
