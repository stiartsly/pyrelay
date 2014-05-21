import sys
import struct
from ctypes import create_string_buffer

# the format of stun message header, which followed 
# by zero or more attributes
#|<---  16 bits ------->|<---- 16 bits  ------>|
#+++++++++++++++++++++++++++++++++++++++++++++++
#<- stun message type ->|<-- message length -->|
#-----------------------------------------------
#<-----             magic cookie        ------>|
#-----------------------------------------------
#<-----            transaction id       ------>|                
#+++++++++++++++++++++++++++++++++++++++++++++++

# the format of the attribute 
#+++++++++++++++++++++++++++++++++++++++++++++++
#<---- attr id      --->|<-- attr length  ---->|
#----------------------------------------------
#<-----     attribute value ...        ------->|
#+++++++++++++++++++++++++++++++++++++++++++++++

# class
mclass_request      = 0b00
mclass_indication   = 0b01
mclass_rsp_suc      = 0b10
mclass_rsp_err      = 0b11

def is_rsp_class(mclass):
    return mclass & 0b10

#method:
method_bind_relay   = 0x01
method_bind_channel = 0x02
method_fwd_data     = 0x05

def get_method(msg_type):
    return (msg_type & 0xfffc) >> 2

def get_mclass(msg_type):
    return msg_type & 0x0003

def get_msgtype(method, mclass):
    return (method << 2) | mclass


#attribute:
attr_error          = 0x0001
attr_peer_idx       = 0x0002
attr_client_idx     = 0x0003
attr_channle_idx    = 0x0004

attr_software       = 0x0101
attr_address        = 0x0102
attr_data           = 0x0103

def get_attr_val(attrs, key):
    if not attrs or key not in attrs:
        return None
    return attrs[key]

def stringed_attr(attr_key):
    return attr_key & 0x0100

len_msg_type    = 2
len_msg_length  = 2
len_msg_cookie  = 4
len_msg_transid = 4
len_msg_header  = 12

len_attr_key    = 2
len_attr_len    = 2

MAGIC_COOKIE = 0x12345678

def generate_transid():
    return 0x13343

class InMsg(object):
    _method  = 0
    _mclass  = 0
    _transid = 0
    _attrs   = None

    _from_buf = None

    def __init__(self, buf):
        self._from_buf = buf
        self._attrs = {}

    def unpack(self):
        def _fmt(key, tlen):
            if stringed_attr(key):
                fmt = str(tlen) + 's'
            else:
                fmt = '!i'
            return fmt

        if len(self._from_buf) < len_msg_header:
            return False

        offset = 0
        mtype,  = struct.unpack_from("!h", self._from_buf, offset)
        offset += len_msg_type
        length, = struct.unpack_from("!h", self._from_buf, offset)
        offset += len_msg_length
        cookie, = struct.unpack_from("!i", self._from_buf, offset)
        offset += len_msg_cookie
        transid,= struct.unpack_from("!i", self._from_buf, offset)
        offset += len_msg_transid

        self._method = get_method(mtype)
        self._mclass = get_mclass(mtype)
        self._transid= transid

        if cookie != MAGIC_COOKIE:
            return False

        if length != len(self._from_buf) - len_msg_header:
            return False
            
        while offset < len(self._from_buf):
            key , = struct.unpack_from("!h", self._from_buf, offset)
            offset += len_attr_key
            tlen, = struct.unpack_from("!h", self._from_buf, offset)
            offset += len_attr_len
            val , = struct.unpack_from(_fmt(key, tlen), self._from_buf, offset)
            offset += tlen 
            self._attrs[key] = val 

        return True

    def method(self): 
        return self._method

    def mclass(self):
        return self._mclass

    def transid(self):
        return self._transid

    def attrs(self):
        return self._attrs

class OutMsg(object):
    _method  = 0
    _mclass  = 0
    _transid = 0
    _attrs   = None
    _raw_buf = None

    def __init__(self, method, mclass, transid=None):
        self._method = method
        self._mclass = mclass
        self._transid= transid
        self._attrs  = {}
        if not transid:
            self._transid = generate_transid()

    def add_attrs(self, attrs):
        self._attrs = attrs
        return self

    def pack(self):

        def _fmt(key, val):
            if stringed_attr(key):
                fmt = str(len(val)) + "s"
            else:
                fmt = "!i"
            return fmt

        def _len(key, val):
            if stringed_attr(key):
                length = len(val)
            else:
                length = 4
            return length

        tlen = 0
        for key in self._attrs:
            val = self._attrs[key]
            tlen += len_attr_key + len_attr_len
           
            if stringed_attr(key):
                tlen += len(val)
            else:
                tlen += 4

        offset = 0
        buf = create_string_buffer(tlen + len_msg_header)
        struct.pack_into("!h", buf, offset, get_msgtype(self._method, self._mclass))
        offset += len_msg_type
        struct.pack_into("!h", buf, offset, tlen)
        offset += len_msg_length
        struct.pack_into("!i", buf, offset, MAGIC_COOKIE)
        offset += len_msg_cookie
        struct.pack_into("!i", buf, offset, self._transid)
        offset += len_msg_transid

        for key in self._attrs:
            val = self._attrs[key]
            struct.pack_into("!h", buf, offset, key)
            offset += len_attr_key
            struct.pack_into("!h", buf, offset, _len(key,val))
            offset += len_attr_len
            struct.pack_into(_fmt(key, val),  buf, offset, val)
            offset += _len(key, val)

        self._raw_buf = buf
        return True

    def to_buf(self):
        return self._raw_buf
