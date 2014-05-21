import sys
import os

from lib.libconfig import *
from lib.librelay  import *
from lib.laundry   import *

config = ProxyConfig.init_singleton("./proxy.conf")
if not config:
    print "failed to load proxy config file."
    exit(-1)

proxy = get_channel_proxy()
if not proxy:
    print "failed to initialized proxy inst."
    exit(-1)

laundry = get_proxyed_laundry()
if not laundry:
    print "failed to initialized laundry inst."
    exit(-1)
laundry.boost()
init_proxy()
laundry.join()


