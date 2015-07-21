"Actions that can be run against entry when popping from  data-queue."
import logging
import os
import os.path
import subprocess
import magic
import shutil
import time
from datetime import datetime

#! from . import irods_utils as iu
from . import submit as ts
from . import diag

import dataq.dqutils as du
import dataq.red_utils as ru

# +++ Add code here if TADA needs to handle additional types of files!!!
def file_type(filename):
    """Return an abstracted file type string.  MIME isn't always good enough."""
    if magic.from_file(filename).decode().find('FITS image data') >= 0:
        return('FITS')
    elif magic.from_file(filename).decode().find('JPEG image data') >= 0:
        return('JPEG')
    elif magic.from_file(filename).decode().find('script text executable') >= 0:
        return('shell script')
    else:
        return('UNKNOWN')
    

##############################################################################

def network_move(rec, qname, **kwargs):
    "Transfer from Mountain to Valley"
    logging.debug('EXECUTING network_move()')
    for p in ['qcfg', 'dirs']:
        if p not in kwargs:
            raise Exception(
                'ERROR: "network_move" Action did not get required '
                +' keyword parameter: "{}" in: {}'
                .format(p, kwargs))
    qcfg=kwargs['qcfg']
    dirs=kwargs['dirs']
    logging.debug('dirs={}'.format(dirs))

    nextq = qcfg[qname]['next_queue']
    dq_host = qcfg[nextq]['dq_host']
    dq_port = qcfg[nextq]['dq_port']
    redis_port = qcfg[nextq]['redis_port']

    source_root = qcfg[qname]['cache_dir']
    pre_action = qcfg[qname].get('pre_action',None)
    sync_root = qcfg[qname]['mirror_dir']
    valley_root = qcfg[nextq]['mirror_dir']
    fname = rec['filename']            # absolute path

    logging.debug('source_root={}, fname={}'.format(source_root, fname))
    if fname.find(source_root) == -1:
        raise Exception('Filename "{}" does not start with "{}"'
                        .format(fname, source_root))

    ifname = os.path.join(sync_root, os.path.relpath(fname, source_root))
    
    logging.debug('pre_action={}'.format(pre_action))
    if pre_action:
        # pre_action is full path to shell script to run.
        # WARNING: a bad script could do bad things to the mountain_cache files!!!
        # Must accept two params:
        #   1. absolute path of file from queue
        #   2. absolute path mountain_cache
        # Stdout and stderr from pre_action will be logged to INFO.
        # Error (non-zero return code) will be logged to ERROR but normal
        # TADA processing will continue.
        try:
            cmdline = [pre_action, fname, source_root]
            diag.dbgcmd(cmdline)
            out = subprocess.check_output(cmdline, stderr=subprocess.STDOUT)
            if len(out) > 0:
                logging.info('pre_action "{}" output: {}'.format(preaction,out))
        except subprocess.CalledProcessError as cpe:
            logging.warning('Failed Transfer pre_action ({} {} {}) {}; {}'
                            .format(pre_action, fname, source_root,
                                    cpe, cpe.output ))
            
    out = None
    try:
        #!iu.irods_put(fname, ifname)
        cmdline = ['rsync', 
                   #! '--acls',
                   '--super',
                   #! '--archive',
                   #! '--group',    # preserve group
                   #! '--owner',    # preserve owner (if run as super-user)
                   '--perms',    # preserve permissions
                   #! '--stats',    # give some file-transfer stats
                   #! '--times',    # preserve modification times
                   ###
                   '--chmod=ugo=rwX',
                   '--compress', # compress file data during the transfer
                   '--contimeout=5',
                   '--password-file', '/etc/tada/rsync.pwd',
                   '--recursive',
                   '--remove-source-files',
                   #sender removes synchronized files (non-dir)
                   '--timeout=20',
                   source_root, sync_root]
        diag.dbgcmd(cmdline)
        tic = time.time()
        out = subprocess.check_output(cmdline,
                                      stderr=subprocess.STDOUT)
        logging.info('rsync completed in {:.2f} seconds'
                     .format(time.time() - tic))
    except Exception as ex:
        logging.warning('Failed to transfer from Mountain ({}) to Valley. '
                        '{}; {}'
                        .format(os.getuid(),
                                ex,
                                #!ex.output.decode('utf-8'),
                                out
                            ))
        # Any failure means put back on queue. Keep queue handling
        # outside of actions where possible.
        raise

    # successfully transfered to Valley
    logging.info('Successfully moved file from {} to {}'
                 .format(fname,sync_root))
    mirror_fname = os.path.join(valley_root,
                                os.path.relpath(fname, source_root))
    try:
        # What if QUEUE is down?!!!
        #!du.push_to_q(dq_host, dq_port, mirror_fname, rec['checksum'])
        ru.push_direct(dq_host, redis_port,
                       mirror_fname, rec['checksum'],
                       qcfg[nextq])
        
        # Files removed by rsync through option '--remove-source-files' above
        #
        #!os.remove(fname)
        #!logging.info('Removed file "{}" from mountain cache'.format(fname))
        #!optfname = fname + ".options"
        #!if os.path.exists(optfname):
        #!    os.remove(optfname)
        #!    logging.debug('Removed options file: {}'.format(optfname))
    except Exception as ex:
        logging.error('Failed to push to queue on {}:{}; {}'
                        .format(dq_host, dq_port, ex ))
        logging.error('push_to_q stack: {}'.format(du.trace_str()))
        raise
    return True


def logsubmit(submitlog, src, dest, comment, fail=False):
    with open(submitlog, mode='a') as f:
        print('{timestamp} {status} {srcfname} {destfname} {msg}'
              .format(timestamp=datetime.now().strftime('%m/%d/%y_%H:%M:%S'),
                      status = 'FAILURE' if fail else 'SUCCESS',
                      srcfname=src,
                      destfname=dest,
                      msg=comment),
              file=f)

    
def submit(rec, qname, **kwargs):
    """Try to modify headers and submit FITS to archive. If anything fails 
more than N times, move the queue entry to Inactive. (where N is the 
configuration field: maximum_errors_per_record)
"""
    #!logging.debug('submit({},{})'.format(rec, qname))
    qcfg = du.get_keyword('qcfg', kwargs)
    dq_host = qcfg[qname]['dq_host']
    dq_port = qcfg[qname]['dq_port']

    noarc_root =  qcfg[qname]['noarchive_dir']
    mirror_root =  qcfg[qname]['mirror_dir']
    submitlog =  qcfg[qname]['submitlog']

    # eg. /tempZone/mountain_mirror/other/vagrant/16/text/plain/fubar.txt
    ifname = rec['filename']            # absolute path (mountain_mirror)
    checksum = rec['checksum']          

    try:
        #! ftype = iu.irods_file_type(ifname)
        ftype = file_type(ifname)
    except Exception as ex:
        logging.error('Execution failed: {}; ifname={}'
                      .format(ex, ifname))
        raise
        
    logging.debug('File type for "{}" is "{}".'
                  .format(ifname, ftype))
    destfname = None
    if 'FITS' == ftype :  # is FITS
        msg = 'FITS_file'
        try:
            destfname = ts.submit_to_archive(ifname, checksum, qname, qcfg)
        except Exception as sex:
            logsubmit(submitlog, ifname, ifname, 'submit_to_archive',
                      fail=True)
            raise sex
        else:
            logging.info('PASSED submit_to_archive; {} as {}'
                         .format(ifname, destfname))
            # successfully transfered to Archive
            os.remove(ifname)
            optfname = ifname + ".options"
            logging.debug('Remove possible options file: {}'.format(optfname))
            if os.path.exists(optfname):
                os.remove(optfname)
            logsubmit(submitlog, ifname, destfname, msg)
    else: # not FITS
        msg = 'non-fits'
        destfname = ifname.replace(mirror_root, noarc_root)
        try:
            os.makedirs(os.path.dirname(destfname), exist_ok=True)
            shutil.move(ifname, destfname)
        except:
            logsubmit(submitlog, ifname, ifname,msg, fail=True)
            logging.warning('Failed to mv non-fits file from mirror on Valley.')
            raise
        logsubmit(submitlog, ifname, destfname, msg)
        # Remove files if noarc_root is taking up too much space (FIFO)!!!
        logging.info('Non-FITS file put in: {}'.format(destfname))
        
    return True
# END submit() action
