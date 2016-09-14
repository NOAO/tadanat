"Actions that can be run against entry when popping from  data-queue."
# 2.4.18
import logging
import os
import os.path
import subprocess
import magic
import socket
import shutil
import time
from pathlib import PurePath
import hashlib
import traceback

import dataq.dqutils as du
import dataq.red_utils as ru

from . import submit as ts
from . import diag
from . import fits_utils as fu
from . import config
from . import exceptions as tex
from . import utils as tut
from . import audit
from . import settings

auditor = audit.Auditor()



##############################################################################
### Actions
###
###   Form: func(queue_entry_dict[filename,checksum], queuename)
###   RETURN: True iff successful
###           False or exception on error
###

def network_move(rec, qname):
    "Transfer from Mountain to Valley"
    logging.debug('EXECUTING network_move()')
    thishost = socket.getfqdn()
    md5sum = rec['checksum']

    auditor.set_fstop(md5sum, 'mountain:cache', thishost)

    tempfname = rec['filename']  # absolute path (in temp cache)
    fname = tempfname.replace('/cache/.queue/', '/cache/')
    shutil.move(tempfname,fname) # from temp (non-rsync) dir to rsync dir
    shutil.move(tempfname+'.yaml', fname+'.yaml')
    source_root = '/var/tada/cache' 
    sync_root =  'rsync://tada@{}/cache'.format(settings.valley_host)
    valley_root = '/var/tada/cache'
    popts, pprms = fu.get_options_dict(fname) # .yaml
    if thishost == settings.valley_host:
        logging.error(('Current host ({}) is same as "valley_host" ({}). '
                      'Not moving file!')
                      .format(thishost, settings.valley_host))
        return None


    logging.debug('source_root={}, fname={}'.format(source_root, fname))
    if fname.find(source_root) == -1:
        raise Exception('Filename "{}" does not start with "{}"'
                        .format(fname, source_root))

    # ifname = os.path.join(sync_root, os.path.relpath(fname, source_root))
    # optfname = ifname + ".options"
    newfname = fname # temp dir, not rsync
    logging.debug('pre_action={}'.format(settings.pre_action))
    if settings.pre_action:
        # pre_action is full path to shell script to run.
        # WARNING: a bad script could do bad things to the
        #    mountain_cache files!!!
        # Script must accept three params:
        #   1. absolute path of file from queue
        #   2. absolute path mountain_cache
        #   3. absolute path of file containing options
        # Stdout and stderr from pre_action will be logged to INFO.
        # Error (non-zero return code) will be logged to ERROR but normal
        # TADA processing will continue.
        try:
            cmdline = [settings.pre_action, fname, source_root,
                       fname+'.options']
            diag.dbgcmd(cmdline)
            bout = subprocess.check_output(cmdline, stderr=subprocess.STDOUT)
            if len(bout) > 0:
                out = bout.decode('utf-8')
                newfname = out.split()[0]
                logging.info('pre_action "{}", newfname={}, output: {}'
                             .format(settings.pre_action, newfname, out))
        except subprocess.CalledProcessError as cpe:
            logging.warning('Failed Transfer pre_action ({} {} {}) {}; {}'
                            .format(settings.pre_action, fname, source_root,
                                    cpe, cpe.output ))
        
    out = None
    try:

        # Use feature of rsync 2.6.7 and later that limits path info
        # sent as implied directories.  The "./" marker in the path
        # means "append path after this to destination prefix to get
        # destination path".
        # e.g. '/var/tada/mountain_cache/./pothiers/1294/'
        rsync_source_path = '/'.join([str(PurePath(source_root)),
                                      '.',
                                      str(PurePath(newfname)
                                          .relative_to(source_root).parent),
                                      ''])
        # The directory of newfname is unique (user/jobid)
        # Copy full contents of directory containing newfname to corresponding
        # directory on remote machine (under mountain_mirror).
        cmdline = ['rsync', 
                   '--super',
                   '--perms',    # preserve permissions
                   '--stats',    # give some file-transfer stats
                   ###
                   '--chmod=ugo=rwX',
                   #!'--compress', # we generally fpack fits files
                   '--contimeout=20',
                   '--password-file', '/etc/tada/rsync.pwd',
                   '--recursive',
                   '--relative',
                   '--exclude=".*"',
                   '--remove-source-files', 
                   #sender removes synchronized files (non-dir)
                   '--timeout=40', # seconds
                   #! '--verbose',
                   #! source_root, sync_root]
                   rsync_source_path,
                   sync_root
                   ]
        diag.dbgcmd(cmdline)
        tic = time.time()
        out = subprocess.check_output(cmdline,
                                      stderr=subprocess.STDOUT)
        logging.debug('rsync completed in {:.2f} seconds'
                      .format(time.time() - tic))
    except Exception as ex:
        logging.warning('Failed to transfer from Mountain to Valley using: {}; '
                        '{}; {}'
                        .format(' '.join(cmdline),
                                ex,
                                out
                            ))
        # Any failure means put back on queue. Keep queue handling
        # outside of actions where possible.
        # raise # Do NOT raise exception since we will re-do rsync next time around
        return False

    # successfully transfered to Valley
    auditor.set_fstop(md5sum, 'valley:cache', settings.valley_host)
    logging.debug('rsync output:{}'.format(out))
    logging.info('Successfully moved file from {} to {}'
                 .format(newfname, sync_root))
    mirror_fname = os.path.join(valley_root,
                                os.path.relpath(newfname, source_root))
    try:
        # What if QUEUE is down?!!!
        ru.push_direct(settings.valley_host, settings.redis_port,
                       mirror_fname, md5sum)
    except Exception as ex:
        logging.error('Failed to push to queue on {}; {}'
                      .format(settings.valley_host, ex))
        logging.error('push_to_q stack: {}'.format(du.trace_str()))
        raise
    auditor.set_fstop(md5sum, 'valley:queue', settings.valley_host)
    return True
    # END network_move

# Done against each record popped from data-queue
def submit(rec, qname):
    try:
        ts.unprotected_submit(rec['filename'], rec['checksum'])
    except tex.IngestRejection as ex:
        tut.log_traceback()        
        try:
            auditor.log_audit(ex.md5sum, ex.origfilename, False, '',
                              ex.errmsg, newhdr=ex.newhdr)
        except Exception as err:
            # At this point, we must ignore the error and move on.
            logging.exception('Error in log_audit after ingest reject; {}'
                              .format(err))
            return False
        
    except Exception as ex:
        logging.error('Do not let errors fall through this far!!!')
        logging.error(traceback.format_exc())
        logging.error(('Failed to run action "submit" from dataq.'
                       ' rec={}; qname={}; {}')
                      .format(rec, qname, ex))
        return False
    return True
