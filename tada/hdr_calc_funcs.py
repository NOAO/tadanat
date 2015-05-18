'''Functions intended to be referenced in Personality files. 

Each function accepts a dictionary of name/values (intended to be from
a FITS header) and returns a dictionary of new name/values.  Fields
(names) may be added but not removed in the new dictionary with
respect to the original. To update the original dict, use python dict update:
   orig.update(new)

In each function of this file:
  orig::    orginal header as a dictionary
  RETURNS:: dictionary that should be used to update the header

These function names MUST NOT CONTAIN UNDERSCORE ("_").  They are
listed by name in option values passed to "lp". Underscores are
expanded to spaces to handle the command line argument limitation.

'''

import logging
from dateutil import tz
import datetime as dt


def addTimeToDATEOBS(orig):
    'Use TIME-OBS for time portion of DATEOBS. Depends on: DATE-OBS, TIME-OBS'
    if ('T' in orig['DATE-OBS']):
        new = dict()
    else:
        new = {'ODATEOBS': orig['DATE-OBS'],            # save original
               'DATE-OBS': orig['DATE-OBS'] + 'T' + orig['TIME-OBS']
           }
    return new
        

#DATEOBS is UTC, so convert DATEOBS to localdate and localtime, then:
#if [ $localtime > 12:00]; then DTCALDAT=localdate; else DTCALDAT=localdate-1 
def DTCALDATfromDATEOBStus(orig):
    'Depends on: DATE-OBS'
    local_zone = tz.gettz('America/Phoenix')
    utc = dt.datetime.strptime(orig['DATE-OBS'], '%Y-%m-%dT%H:%M:%S.%f')
    utc = utc.replace(tzinfo=tz.tzutc()) # set UTC zone
    localdt = utc.astimezone(local_zone)
    if localdt.time().hour > 12:
        caldate = localdt.date()
    else:
        caldate = localdt.date() - dt.timedelta(days=1)
    #!logging.debug('localdt={}, DATE-OBS={}, caldate={}'
    #!              .format(localdt, orig['DATE-OBS'], caldate))
    new = {'DTCALDAT': caldate.isoformat()}
    return new

def PROPIDtoDT(orig):
    'Depends on: PROPID'
    return {'DTPROPID': orig['PROPID'] }

def INSTRUMEtoDT(orig):
    'Depends on: INSTRUME'
    return {'DTINSTRU': orig['INSTRUME'] }


def IMAGTYPEtoOBSTYPE(orig):
    'Depends on: IMAGETYP'
    return {'OBSTYPE': orig['IMAGETYP']  }


def bokOBSID(orig):
    "Depends on DATE-OBS"
    return {'OBSID': 'bok23m.'+orig['DATE-OBS'] }

def DTTELESCfromINSTRUME(orig):
    "Instrument specific calculations. Depends on: INSTRUME, OBSID"
    new = dict() # Fields to calculate
    instrument = orig['INSTRUME'].lower()

    # e.g. OBSID = 'kp4m.20141114T122626'
    # e.g. OBSID = 'soar.sam.20141220T015929.7Z'
    #!tele, dt_str = orighdr['OBSID'].split('.')
    if 'cosmos' == instrument:
        tele, dt_str = orig['OBSID'].split('.')
        new['DTTELESC'] = tele
    elif 'mosaic1.1' == instrument:
        tele, dt_str = orig['OBSID'].split('.')
        new['DTTELESC'] = tele
    elif 'soi' == instrument:
        tele, inst, dt_str1, dt_str2 = orig['OBSID'].split('.')
        new['DTTELESC'] = tele
#!    elif '90prime' == instrument: # BOK
#!        # FILENAME='bokrm.20140425.0119.fits' / base filename at acquisition
#!        tele = orig.get('TELESCOP', None)
#!        if tele == None:
#!            tele, datestr, *rest = orig['FILENAME'].split('.')
#!        new['DTTELESC'] = tele
#!        new['OBSTYPE'] = orig.get('IMAGETYP','object')
    else:
        pass

    new['DTINSTRU'] = instrument # eg. 'NEWFIRM'
    return new


    