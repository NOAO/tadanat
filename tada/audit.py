"""Suppport audit records.  There are two flavors.  One is in
sqllite DB on each valley machine.  One is via MARS service (a
composite of all domes and valleys).
"""

import logging
import sqlite3
import datetime
#import urllib.request
#import json
import requests
import os.path
from . import ingest_decoder as dec


class Auditor():
    "Maintain audit records both locally (valley) and via MARS service"
    
    def __init__(self, mars_host, mars_port, use_service):
        self.con = sqlite3.connect('/var/log/tada/audit.db')
        self.mars_port = mars_port
        self.mars_host = mars_host
        self.do_svc = use_service #if pprms.get('do_audit',False):

#    def log_audit(self, localfits, origfname, success, archfile, err, hdr, newhdr):
    def log_audit(self, prms, success, archfile, err, hdr, newhdr):
        """Log audit record to MARS.
        prms:: dict[filename]:: absolute dome filename
               dict[md5sum]:: checksum of dome file
        success:: bool; True iff ingest succeeded
        archfile:: base filename of file in archive (if ingested)
        hdr:: dict; orginal FITS header field/values
        newhdr:: dict; modified FITS header field/values
        """
        try:
            origfname = prms.get('filename','NA-in-yaml') # "filename" not provided in yaml file
            md5sum = prms.get('md5sum', 'NA-in-yaml') # "md5sum" not provided in yaml file
            archerr = str(err)
            logging.debug('log_audit({},{},{},{},{},{} do_svc={})'
                          .format(origfname, success, archfile, archerr,
                                  hdr, newhdr, self.do_svc))
            if not success:
                logging.error('log_audit; archive ingest error: '
                              .format(archerr))

            now = datetime.datetime.now().isoformat()
            today = datetime.date.today().isoformat()

            obsday = newhdr.get('DTCALDAT',hdr.get('DTCALDAT', today))
            if ('DTCALDAT' not in newhdr) and ('DTCALDAT' not in hdr):
                logging.error('Could not find DTCALDAT in hdr {}, using TODAY'
                              .format(origfname))
            tele = newhdr.get('DTTELESC',hdr.get('DTTELESC', 'unknown'))
            instrum = newhdr.get('DTINSTRU',hdr.get('DTINSTRU', 'unknown'))
            recdic = dict(md5sum=md5sum,
                          # obsday,telescope,instrument; provided by dome
                          #    unless dome never created audit record, OR
                          #    prep error prevented creating new header
                          obsday=obsday,
                          telescope=tele.lower(),
                          instrument=instrum.lower(),
                          #
                          srcpath=origfname,
                          recorded=now, # should be when DOME created record
                          #
                          submitted=now,
                          success=success,
                          archerr=archerr,
                          errcode=dec.errcode(archerr),
                          archfile=os.path.basename(archfile),
                          metadata=hdr)
            logging.debug('log_audit: recdic={}'.format(recdic))
            try:
                self.update_local(recdic)
            except Exception as ex:
                logging.error('Could not update local audit.db; {}'.format(ex))

            if self.do_svc:
                logging.debug('Update audit via service')
                try:
                    self.update_svc(recdic)
                except Exception as ex:
                    logging.error('Could not update remote audit record; {}'.format(ex))
            else:
                logging.debug('Did not update via audit service')
        except Exception as ex:
            logging.error('auditor.log_audit() failed: {}'.format(ex))

    # FIRST something like: sqlite3 audit.db < sql/audit-schema.sql
    def update_local(self, recdic):
        "Add audit record to local sqlite DB. (in case service is down)"
        logging.debug('update_local ({})'.format(recdic,))
        fnames = ['md5sum',
                  'obsday', 'telescope', 'instrument',
                  'srcpath', 'recorded', 'submitted',
                  'success',  'archerr', 'archfile',
        ]
        values = [recdic[k] for k in fnames]
        #! logging.debug('update_local ({}) = {}'.format(fnames,values))
        # replace the non-primary key values with new values.
        sql = ('INSERT OR REPLACE INTO audit ({}) VALUES ({})'
               .format(','.join(fnames),
                       (('?,' * len(fnames))[:-1])))
        self.con.execute(sql, tuple(values))
        self.con.commit()
    
    def update_svc(self, recdic):
        """Add audit record to svc."""
        if self.mars_host == None or self.mars_port == None:
            logging.error('Missing AUDIT host ({}) or port ({}).'
                          .format(self.mars_host, self.mars_port))
            return False
        uri = 'http://{}:{}/audit/update/'.format(self.mars_host, self.mars_port)
        fnames = ['md5sum',
                  'obsday', 'telescope', 'instrument',
                  'srcpath', 'recorded', 'submitted',
                  'success', 'archerr', 'errcode', 'archfile',
                  'metadata',
        ]
        ddict = dict()
        for k in fnames:
            ddict[k] = recdic[k]
        logging.debug('Adding audit record via {}; json={}'.format(uri, ddict))
        try:
            req = requests.post(uri, json=ddict)
            #logging.debug('auditor.update_svc: response={}'.format(req.text))
            return req.text
        except  Exception as err:
            logging.error('AUDIT: Error contacting service via "{}"; {}'
                          .format(uri, str(err)))
            return False
        return True



        


