import sys
import os

from lib.libconfig import *
from lib.librelay  import *
from lib.laundry   import *

config = RelayConfig.init_singleton("./relay.conf")
if not config:
    print "failed to load relay config file."
    exit(-1)

relay = RelayedListenningChannel.singleton()
if not relay:
    print "failed to initialized relay inst."
    exit(-1)

laundry = get_relayed_laundry()
if not laundry:
    print "failed to initialized laundry inst."
    exit(-1)
laundry.boost()
laundry.join()


