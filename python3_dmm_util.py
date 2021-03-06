#!/usr/bin/env python3
# vim: set fileencoding=utf-8 :

import serial
import time
from time import gmtime, strftime
import struct
import sys
import datetime
from calendar import timegm

def usage():
  print ("Usage: dmm_util info                                        : Display info about the meter")
  print ("       dmm_util recordings [index|name] ...                 : Display one or all recordings (index from 0)")
  print ("       dmm_util saved_measurements [index|name] ...         : Display one or all saved measurements (index from 0)")
  print ("       dmm_util saved_min_max [index|name] ...              : Display one or all saved min max measurements (index from 0)")
  print ("       dmm_util saved_peak [index|name] ...                 : Display one or all saved peak measurements (index from 0)")
  print ("       dmm_util measure_now                                 : Display the current meter value" )
  print ("       dmm_util set <company|contact|operator|site> <value> : Set meter contact info")
  print ("       dmm_util sync_time                                   : Sync the clock on the DMM to the computer clock")
  print ("")
  sys.exit()

def do_sync_time():
  lt = timegm(datetime.datetime.now().utctimetuple())
  cmd = 'mp clock,' + str(lt) + '\r'
  ser.write(cmd.encode())
  time.sleep (0.1)
  res=ser.read(2)
  if res == b'0\r': print ("Sucsessfully synced the clock of the DMM")
  
def do_measure_now():
  while True:
    try:
      res = qddb()
      print (time.strftime('%Y-%m-%d %H:%M:%S %z',res['readings']['LIVE']['ts']), \
            ":", \
            res['readings']['LIVE']['value'], \
            res['readings']['LIVE']['unit'], \
            "=>", \
            res['prim_function'])
    except KeyboardInterrupt:
      sys.exit()

def qddb():
  bytes = meter_command("qddb")

  reading_count = get_u16(bytes, 32)
  if len(bytes) != reading_count * 30 + 34:
    raise ValueError('By app: qddb parse error, expected %d bytes, got %d' % ((reading_count * 30 + 34),len(bytes)))
  tsval = get_double(bytes, 20)
  # all bytes parsed
  return {
    'prim_function' : get_map_value('primfunction', bytes, 0),
    'sec_function' : get_map_value('secfunction', bytes, 2),
    'auto_range' : get_map_value('autorange', bytes, 4),
    'unit' : get_map_value('unit', bytes, 6),
    'range_max' : get_double(bytes, 8),
    'unit_multiplier' : get_s16(bytes, 16),
    'bolt' : get_map_value('bolt', bytes, 18),
#    'ts' : (tsval < 0.1) ? nil : parse_time(tsval), # 20
    'ts' : 0,
    'mode' : get_multimap_value('mode', bytes, 28),
    'un1' : get_u16(bytes, 30),
    # 32 is reading count
    'readings' : parse_readings(bytes[34:])
  }

def do_set():
  property = sys.argv[2]
  value = sys.argv[3]
  if argc != 4:
    usage()
    sys.exit()
  if property not in ["company", "site", "operator", "contact"]:
    usage()
    sys.exit()
  cmd = 'mpq ' + property + ",'" + value + "'\r"
  ser.write(cmd)
  time.sleep (0.1)
  res=ser.read(2)
  if res[0] == '0': print ("Sucsessfully set",property, "value")


def do_info():
  info = id()
  print ("Model:",info['model_number'])
  print ("Software Version:",info['software_version'])
  print ("Serial Number:",info['serial_number'])
  print ("Current meter time:",time.strftime('%Y-%m-%d %H:%M:%S %z',time.gmtime(int(clock()))))
  print ("Company:",meter_command("qmpq company")[0].lstrip("'").rstrip("'"))
  print ("Contact:",meter_command("qmpq contact")[0].lstrip("'").rstrip("'"))
  print ("Operator:",meter_command("qmpq operator")[0].lstrip("'").rstrip("'"))
  print ("Site:",meter_command("qmpq site")[0].lstrip("'").rstrip("'"))

def id():
  res = meter_command("ID")
  return {'model_number' : res[0], 'software_version' : res[1], 'serial_number' : res[2]}

def qsls():
  res = meter_command("qsls")
  return {'nb_recordings':res[0],'nb_min_max':res[1],'nb_peak':res[2],'nb_measurements':res[3]}

def clock():
  res = meter_command("qmp clock")
  return res[0]

def qsrr(reading_idx, sample_idx):
#  print "in qsrr reading_idx=",reading_idx,",sample_idx",sample_idx
  res = meter_command("qsrr " + reading_idx + "," + sample_idx)

  if len(res) != 146:
    raise ValueError('By app: Invalid block size: %d should be 146' % (len(res)))
  # All bytes parsed - except there seems to be single byte at end?
  return {
    'start_ts' :  parse_time(get_double(res, 0)),
    'end_ts' :  parse_time(get_double(res, 8)),
    'readings' : parse_readings(res[16:16 + 30*3]),
    'duration' : get_u16(res, 106) * 0.1,
    'un2' : get_u16(res, 108),
    'readings2' : parse_readings(res[110:110 +30]),
    'record_type' :  get_map_value('recordtype', res, 140),
    'stable'   : get_map_value('isstableflag', res, 142),
    'transient_state' : get_map_value('transientstate', res, 144)
  }

def parse_readings(reading_bytes):
#  print "in parse_readings,reading_bytes=",reading_bytes,"lgr:",len(reading_bytes)
  readings = {}
  chunks, chunk_size = len(reading_bytes), 30
  l = [ reading_bytes[i:i+chunk_size] for i in range(0, chunks, chunk_size) ]
  for r in l:
    readings[get_map_value('readingid', r, 0)] = {
                           'value' : get_double(r, 2),
                           'unit' : get_map_value('unit', r, 10),
                           'unit_multiplier' : get_s16(r, 12),
                           'decimals' : get_s16(r, 14),
                           'display_digits' : get_s16(r, 16),
                           'state' : get_map_value('state', r, 18),
                           'attribute' : get_map_value('attribute', r, 20),
                           'ts' : get_time(r, 22)
    }
  return readings

def get_map_value(map_name, string, offset):
#  print "map_name",map_name,"in map_cache",map_name in map_cache
  if map_name in map_cache:
    map = map_cache[map_name]
  else:
    map = qemap(map_name)
    map_cache[map_name] = map
  value = str(get_u16(string, offset))
  if value not in map:
    raise ValueError('By app: Can not find key %s in map %s' % (value, map_name))
#  print "--->",map_name,value,map[value]
  return map[value]

def get_multimap_value(map_name, string, offset):
#  print "in get_multimap_value,map_name=",map_name
#  print "map_name",map_name,"in map_cache",map_name in map_cache
  if map_name in map_cache:
    map = map_cache[map_name]
  else:
    map = qemap(map_name)
    map_cache[map_name] = map
#  print "in get_multimap_value,map=",map
  value = str(get_u16(string, offset))
#  print "in get_multimap_value,value=",value
  if value not in map:
    raise ValueError('By app: Can not find key %s in map %s' % (value, map_name))
  ret = []
  ret.append(map[value])
#  print "in get_multimap_value,ret=",ret
#  print "+++>",value,map[value],"ret",ret
  return ret

def qemap(map_name):
  res = meter_command("qemap " + str(map_name))
#  print "Traitement de la map: ",map_name
#  print "res dans qemap=",res
#  print "in qemap. Longueur=",len(res)
  entry_count = int(res.pop(0))
#  print "in qemap. entry_count=",entry_count
  if len(res) != entry_count *2:
    raise ValueError('By app: Error parsing qemap')
  map = {}
  for i in range(0, len(res), 2):
    map[res[i]]=res[i+1]
#  print "map dans qemap:",map
  return map

def get_s16(string, offset): # Il faut valider le portage de cette fonction
  val = get_u16(string, offset)
#  print "val in get_s16 avant: ",val
#  print "val in get_s16 pendant: ",val & 0x8000
  if val & 0x8000 != 0:
    val = -(0x10000 - val)
#  print "val in get_s16 ares: ",val
  return val

def get_u16(string, offset):
  endian = string[offset+1:offset-1:-1] if offset > 0 else string[offset+1::-1]
  return struct.unpack('!H', endian)[0]

def get_double(string, offset):
  endian_l = string[offset+3:offset-1:-1] if offset > 0 else string[offset+3::-1]
  endian_h = string[offset+7:offset+3:-1]
  endian = endian_l + endian_h
  return struct.unpack('!d', endian)[0]

def get_time(string, offset):
  return parse_time(get_double(string, offset))

def parse_time(t):
  return time.gmtime(t)

def qrsi(idx):
  res = meter_command('qrsi '+idx)
  reading_count = get_u16(res, 76)
#  print "reading_count",reading_count
  if len(res) < reading_count * 30 + 78:
    raise ValueError('By app: qrsi parse error, expected at least %d bytes, got %d' % (reading_count * 30 + 78, len(res)))
  return {
    'seq_no' : get_u16(res, 0),
    'un2' : get_u16(res, 2),
    'start_ts' : parse_time(get_double(res, 4)),
    'end_ts' : parse_time(get_double(res, 12)),
    'sample_interval' : get_double(res, 20),
    'event_threshold' : get_double(res, 28),
    'reading_index' : get_u16(res, 36), # 32 bits?
    'un3' : get_u16(res, 38),
    'num_samples' : get_u16(res, 40),  # Is this 32 bits? Whats in 42
    'un4' : get_u16(res, 42),
    'prim_function' : get_map_value('primfunction', res, 44),
    'sec_function' : get_map_value('secfunction', res, 46), # sec?
    'auto_range' : get_map_value('autorange', res, 48),
    'unit' : get_map_value('unit', res, 50),
    'range_max ' : get_double(res, 52),
    'unit_multiplier' : get_s16(res, 60),
    'bolt' : get_map_value('bolt', res, 62),  #bolt?
    'un8' : get_u16(res, 64),  #ts3?
    'un9' : get_u16(res, 66),  #ts3?
    'un10' : get_u16(res, 68),  #ts3?
    'un11' : get_u16(res, 70),  #ts3?
    'mode' : get_multimap_value('mode', res, 72),
    'un12' : get_u16(res, 74),
    # 76 is reading count
    'readings' : parse_readings(res[78:78+reading_count * 30]),
    'name' : res[(78 + reading_count * 30):]
    }

def qsmr(idx):
  # Get saved measurement
  res = meter_command('qsmr '+idx)

  reading_count = get_u16(res, 36)
  if len(res) < reading_count * 30 + 38:
    raise ValueError('By app: qsmr parse error, expected at least %d bytes, got %d' % (reading_count * 30 + 78, len(res)))

  return { '[seq_no' : get_u16(res,0),
    'un1' : get_u16(res,2),   # 32 bit?
    'prim_function' :  get_map_value('primfunction', res,4), # prim?
    'sec_function' : get_map_value('secfunction', res,6), # sec?
    'auto_range' : get_map_value('autorange', res, 8),
    'unit' : get_map_value('unit', res, 10),
    'range_max' : get_double(res, 12),
    'unit_multiplier' : get_s16(res, 20),
    'bolt' : get_map_value('bolt', res, 22),
    'un4' : get_u16(res,24),  # ts?
    'un5' : get_u16(res,26),
    'un6' : get_u16(res,28),
    'un7' : get_u16(res,30),
    'mode' : get_multimap_value('mode', res,32),
    'un9' : get_u16(res,34),
    # 36 is reading count
    'readings' : parse_readings(res[38:38 + reading_count * 30]),
    'name' : res[(38 + reading_count * 30):]
  }

def do_min_max_cmd(cmd, idx):
  res = meter_command(cmd + " " + idx)
  # un8 = 0, un2 = 0, always bolt
  reading_count = get_u16(res, 52)
  if len(res) < reading_count * 30 + 54:
    raise ValueError('By app: qsmr parse error, expected at least %d bytes, got %d' % (reading_count * 30 + 54, len(res)))

  # All bytes parsed
  return { 'seq_no' : get_u16(res, 0),
    'un2' : get_u16(res, 2),      # High byte of seq no?
    'ts1' : parse_time(get_double(res, 4)),
    'ts2' : parse_time(get_double(res, 12)),
    'prim_function' : get_map_value('primfunction', res, 20),
    'sec_function' : get_map_value('secfunction', res, 22),
    'autorange' : get_map_value('autorange', res, 24),
    'unit' : get_map_value('unit', res, 26),
    'range_max ' : get_double(res, 28),
    'unit_multiplier' : get_s16(res, 36),
    'bolt' : get_map_value('bolt', res, 38),
    'ts3' : parse_time(get_double(res, 40)),
    'mode' : get_multimap_value('mode', res, 48),
    'un8' : get_u16(res, 50),
    # 52 is reading_count
    'readings' : parse_readings(res[54:54 + reading_count * 30]),
    'name' : res[(54 + reading_count * 30):]
    }

def do_saved_peak():
  do_saved_min_max_peak('nb_peak', 'qpsi')

def do_saved_min_max():
  do_saved_min_max_peak('nb_min_max', 'qmmsi')

def do_saved_min_max_peak(field, cmd):
  nb_min_max = int(qsls()[field])
  interval = []
  for i in range(0,nb_min_max):
    interval.append(str(i))
  found = False
  if argc == 2:
    series = interval
  else:
    series = sys.argv[2:]

  for i in series:
    if i.isdigit():
      measurement = do_min_max_cmd(cmd,str(i))
      print_min_max_peak(measurement)
      found = True
    else:
      for j in interval:
        measurement = do_min_max_cmd(cmd,str(j))
        if measurement['name'] == i.encode():
          found = True
          print_min_max_peak(measurement)
          break
  if not found:
    print ("Saved names not found")
    sys.exit()

def print_min_max_peak(measurement):
  print (measurement['name'], 'start', time.strftime('%Y-%m-%d %H:%M:%S %z',measurement['ts1']), measurement['autorange'], 'Range', int(measurement['range_max ']), measurement['unit'])
  print_min_max_peak_detail(measurement, 'PRIMARY')
  print_min_max_peak_detail(measurement, 'MAXIMUM')
  print_min_max_peak_detail(measurement, 'AVERAGE')
  print_min_max_peak_detail(measurement, 'MINIMUM')
  print (measurement['name'], 'end', time.strftime('%Y-%m-%d %H:%M:%S %z',measurement['ts2']))

def print_min_max_peak_detail(measurement, detail):
  print ('\t',detail, \
        measurement['readings'][detail]['value'], \
        measurement['readings'][detail]['unit'], \
        time.strftime('%Y-%m-%d %H:%M:%S %z',measurement['readings'][detail]['ts']))

def do_saved_measurements():
  nb_measurements = int(qsls()['nb_measurements'])
  interval = []
  for i in range(0,nb_measurements):
    interval.append(str(i))
  found = False
  if argc == 2:
    series = interval
  else:
    series = sys.argv[2:]

  for i in series:
    if i.isdigit():
      measurement = qsmr(str(i))
      print (measurement['name'], \
          time.strftime('%Y-%m-%d %H:%M:%S %z',measurement['readings']['PRIMARY']['ts']), \
          ":", \
          measurement['readings']['PRIMARY']['value'], \
          measurement['readings']['PRIMARY']['unit'])
      found = True
    else:
      for j in interval:
        measurement = qsmr(str(j))
        if measurement['name'] == i.encode():
          found = True
          print (measurement['name'], \
              time.strftime('%Y-%m-%d %H:%M:%S %z',measurement['readings']['PRIMARY']['ts']), \
              ":", \
              measurement['readings']['PRIMARY']['value'], \
              measurement['readings']['PRIMARY']['unit'])
          break
  if not found:
    print ("Saved names not found")
    sys.exit()

def do_recordings():
  nb_recordings = int(qsls()['nb_recordings'])
  interval = []
  for i in range(0,nb_recordings):
    interval.append(str(i))
  found = False
  if argc == 2:
    series = interval
  else:
    series = sys.argv[2:]

  for i in series:
    if i.isdigit():
      recording = qrsi(str(i))
      print ("%s (detail) [%s - %s] : %d measurements" % (recording['name'],time.strftime('%Y-%m-%d %H:%M:%S %z',recording['start_ts']),time.strftime('%Y-%m-%d %H:%M:%S %z',recording['end_ts']),recording['num_samples']))

      for k in range(0,recording['num_samples']):
        measurement = qsrr(str(recording['reading_index']), str(k))
        print (time.strftime('%Y-%m-%d %H:%M:%S %z', measurement['start_ts']), \
              measurement['readings2']['PRIMARY']['value'], \
              measurement['readings2']['PRIMARY']['unit'], \
              measurement['readings']['MAXIMUM']['value'], \
              measurement['readings']['MAXIMUM']['unit'], \
              measurement['readings']['AVERAGE']['value'], \
              measurement['readings']['AVERAGE']['unit'], \
              measurement['readings']['MINIMUM']['value'], \
              measurement['readings']['MINIMUM']['unit'], \
              measurement['duration'],)
        print ('INTERVAL' if measurement['record_type'] == 'INTERVAL' else measurement['stable'])
      print
      found = True
    else:
      for j in interval:
        recording = qrsi(str(j))
        if recording['name'] == i.encode():
          found = True
          print ("%s (detail) [%s - %s] : %d measurements" % (recording['name'],time.strftime('%Y-%m-%d %H:%M:%S %z',recording['start_ts']),time.strftime('%Y-%m-%d %H:%M:%S %z',recording['end_ts']),recording['num_samples']))
          for k in range(0,recording['num_samples']):
            measurement = qsrr(str(recording['reading_index']), str(k))
            print (time.strftime('%Y-%m-%d %H:%M:%S %z', measurement['start_ts']), \
                  measurement['readings2']['PRIMARY']['value'], \
                  measurement['readings2']['PRIMARY']['unit'], \
                  measurement['readings']['MAXIMUM']['value'], \
                  measurement['readings']['MAXIMUM']['unit'], \
                  measurement['readings']['AVERAGE']['value'], \
                  measurement['readings']['AVERAGE']['unit'], \
                  measurement['readings']['MINIMUM']['value'], \
                  measurement['readings']['MINIMUM']['unit'], \
                  measurement['duration'],)
            print ('INTERVAL' if measurement['record_type'] == 'INTERVAL' else measurement['stable'])
          print
          break
  if not found:
    print ("Saved names not found")
    sys.exit()

def data_is_ok(data):
  # No status code yet
  if len(data) < 2: return False

  # Non-OK status
  if len(data) == 2 and chr(data[0]) != '0' and chr(data[1]) == "\r": return True

  # Non-OK status with extra data on end
  if len(data) > 2 and chr(data[0]) != '0':
    raise ValueError('By app: Error parsing status from meter (Non-OK status with extra data on end)')

  # We should now be in OK state
  if not data.startswith(b"0\r"):
    raise ValueError('By app: Error parsing status from meter (status:%c size:%d)' % (data[0], len(data)))

  return len(data) >= 4 and chr(data[-1]) == '\r'

def read_retry():
  retry_count = 0
  data = b''

  # First sleep is longer to permit data to be available
  time.sleep (0.03)
  while retry_count < 500 and not data_is_ok(data):
    bytes_read = ser.read(ser.inWaiting())
    data += bytes_read
    if data_is_ok(data): return data
    time.sleep (0.01)
    retry_count += 1
  if len(data) > 1:
    raise ValueError('By app: Error parsing status from meter:  %c %d %r %r' % (chr(data[0]),len(data),chr(data[1]) == '\r', chr(data[-1]) == '\r'))
  else:
    raise ValueError('By app: Error parsing status from meter, no data')

def meter_command(cmd):
#  print ("cmd=",cmd)
  ser.write(cmd.encode()+b'\r')
  data = read_retry()
  if data == b'':
    raise ValueError('By app: Did not receive data from meter')
  status = chr(data[0])
  if status != '0':
    print ("Command: %s failed. Status=%c" % (cmd, status))
    sys.exit()
  if chr(data[1]) != '\r':
    raise ValueError('By app: Did not receive complete reply from meter')
  binary = data[2:4] == b'#0'

  if binary:
    return data[4:-1]
  else:
    data = [i for i in data[2:-1].decode().split(',')]
    return data


argc = len(sys.argv)
if argc == 1:
   usage();
   exit

switch={'recordings':do_recordings,'saved_measurements':do_saved_measurements,'saved_min_max':do_saved_min_max,'saved_peak':do_saved_peak,'info':do_info,'sync_time':do_sync_time,'set':do_set,'measure_now':do_measure_now}

#serial port settings
try:
  ser = serial.Serial(port='/dev/cu.usbserial-AK05FTGH', baudrate=115200, bytesize=8, parity='N', stopbits=1, timeout=0.01, rtscts=False, dsrdtr=False)
except serial.serialutil.SerialException as err:
  print ('Serial Port /dev/cu.usbserial-AK05FTGH does not respond')
  print (err)
  sys.exit()

map_cache = {}

if sys.argv[1] in switch:
  switch[sys.argv[1]]()
else:
  usage()
  sys.exit()

