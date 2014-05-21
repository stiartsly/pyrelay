import sys
import logging

class Log:
    logger = None

    def __init__(self, module, level=logging.DEBUG):
        self.logger = logging.getLogger(module)
        self.logger.setLevel(level)

        ch = logging.StreamHandler()
        ch.setLevel(level)

        fmter = logging.Formatter('[%(name)s]: %(message)s')
        ch.setFormatter(fmter)
        self.logger.addHandler(ch)

    def log(self, msg):
        self.logger.info(msg)

