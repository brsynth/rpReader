from os import path as os_path
from os import mkdir as os_mkdir
from os import remove as os_rm
from rdkit.Chem import MolFromSmiles, MolFromInchi, MolToSmiles, MolToInchi, MolToInchiKey, AddHs
from csv import DictReader as csv_DictReader
from csv import reader as csv_reader
from logging import getLogger as logging_getLogger
from json import dump as json_dump
from json import load as json_load
from gzip import open as gzip_open
from urllib.request import urlretrieve as urllib_request_urlretrieve
from re import findall as re_findall
from tarfile import open as tarfile_open
from shutil import move as shutil_move
from shutil import rmtree as shutil_rmtree
import sys
import time
from itertools import chain as itertools_chain
from brs_utils import print_OK, print_FAILED, download, file_length
from requests import exceptions as r_exceptions
from tarfile import open as tf_open
from redis import StrictRedis
from credisdict import CRedisDict, wait_for_redis
import redis_server
from subprocess import run as proc_run
from subprocess import Popen,PIPE
from argparse import ArgumentParser as argparse_ArgParser
from hashlib import sha512
from pathlib import Path


#######################################################
################### rpCache  ##########################
#######################################################


def add_arguments(parser):
    parser.add_argument('-sm', '--store_mode', type=str, default='file',
                        help='data storage mode: file or db')
    parser.add_argument('--gen_cache', action='store_true',
                        help='generate the cache and exits')
    parser.add_argument('-p', '--print', type=bool, default=False,
                        help='print additional informations')
    return parser

def build_parser():
    return add_arguments(argparse_ArgParser('Python script to pre-compute data'))

# def entrypoint(args=sys.argv[1:]):
#     parser = build_parser()
#
#     params = parser.parse_args(args)
#
#     rpcache = rpCache(params.store_mode, params.print)
#
# ##
# #
# #
# if __name__ == "__main__":
#     entrypoint()

## Class to generate the cache
#
# Contains all the functions that parse different files, used to calculate the thermodynamics and the FBA of the
#the other steps. These should be called only when the files have changes
class rpCache:

    logger = logging_getLogger(__name__)
    logger.info('Started instance of rpCache')

    _input_cache_url = 'ftp://ftp.vital-it.ch/databases/metanetx/MNXref/3.2/'
    _cache_url       = 'https://github.com/brsynth/rpCache-data/raw/master/'

    # static attribues
    _convertMNXM = {'MNXM162231': 'MNXM6',
                    'MNXM84': 'MNXM15',
                    'MNXM96410': 'MNXM14',
                    'MNXM114062': 'MNXM3',
                    'MNXM145523': 'MNXM57',
                    'MNXM57425': 'MNXM9',
                    'MNXM137': 'MNXM588022'}

    # name: sha512sum
    _input_cache_files = {
            'chem_xref.tsv':    '8011352745fdac0f29c710e6bc589684371531fd5a1e99d17ce92fd4382148563cc0089fde394a7cf5f89d31344d521e007faf2066e22073e07309001d9eb7fa',
            'reac_xref.tsv':    '44fe0170dc9a13c10dbbe2435e407286c272c3e834d1696fad102c8a366d51717ace3da37cec31ab8ab2420be440c483f7c0882e34b2e38493a7c0df56583dac',
            'rr_compounds.tsv': '4642f694fd3108e897ba414d0b8ffa78100554d8cd1950315e383e8e8b2c6a744ec983eb1b634ac1636de4577c99fa5ed6a012a85e2f5879168ed1a4b4799a27',
            'chem_prop.tsv':    '535d0ce9f5cf120160559dbb9b09925b2ccb7bc54e83cd206c50a9bbd9c16981adb47e24e1d9db953f293c8e6973e3a6ec4e85d1b64416ae73d9cb67f8840097',
            'rules_rall.tsv':   '1795fb190ac6f798592f994c96d4e9678ec8d7fd99011dc128faf79b9a19d73296cfa204dd8483ff9e56797903c77d5038ed782dcf42d5dea13daecdba77e95f',
            'comp_xref.tsv':    'e8ca37592d92afb9f1c30ae26980c29fd139b08b36daded1706fbe02784b4b58f8fb9d765fc5397041cb53435ef53ab68d7d5d932d21e2ce3994a6aef364f736',
            'rxn_recipes.tsv':  'dbc0a8acb1504fa5745ecf14a99aeb9fb5dcc89e8527216f0f9c87c590910840b547c984311fa0d3651d94df2dfbac9430e803f3b807499f3c925910f8f926bd'
            }

    # name: sha512sum
    _cache_files = {
            'deprecatedMNXM_mnxm': '698a3e83cf4f9206ea2644c9c35a9af53957838baaae6efb245d02b6b8d0ea8b25c75008e562b99ba3e0189e50ee47655376f2d0635f6206e0015f91f0e4bad8',
            'deprecatedMNXR_mnxr': '51554c6f6ae99c6755da7496208b3feec30547bc4cf3007d9fd30f46fa4c0cc73bad5aeb743dca07e32711c4346504296bee776d135fb18e96c891a0086fc87e',
            'mnxm_strc':           '0021ef63165d75ee6b8c209ccf14b8a1b8b7b263b4077f544729c47b5525f66511c3fa578fd2089201abb61693085b9912639e62f7b7481d06ad1f38bfc2dd8e',
            'chemXref':            '7d559cc7389c0cb2bd10f92e6e845bb5724be64d1624adc4e447111fc63599bb69396cd0cc3066a6bb19910c00e266c97e21b1254d9a6dc9da3a8b033603fcff',
            'chebi_mnxm':          '587d6c5206ee94e63af6d9eaf49fd5e2ca417308b3ece8a7f47e916c42376e2c8635a031ce26dc815cd7330f2323054a44d23951e416a9a29c5a9a2ab51e8953',
            'rr_reactions':        '8783aaa65a281c4a7ab3a82a6dc99620418ed2be4a739f46db8ee304fcb3536a78fed5a955e1c373a20c3e7d3673793157c792b4429ecb5c68ddaddb1a0f7de7',
            'inchikey_mnxm':       '8007480fc607caf41f0f9a93beb66c7caa66c37a3d01a809f6b94bc0df469cec72091e8cc0fbabb3bd8775e9776b928ecda2779fc545c7e4b9e71c504f9510ce',
            'compXref':            'afc2ad3d31366a8f7fe1604fa49c190ade6d46bc8915f30bd20fdfdfc663c979bb10ca55ad10cadec6002a17add46639c70e7adf89cb66c57ed004fd3e4f0051',
            'name_compXref':       '81c673fe1940e25a6a9722fd74b16bc30e1590db0c40810f541ad4ffba7ae04c01268b929d4bf944e84095a0c2a1d0079d1861bc1df3e8308fbb6b35e0aaf107',
            'full_reactions':      '599e4de4935d2ba649c0b526d8aeef6f0e3bf0ed9ee20adad65cb86b078ac139e4cc9758945c2bb6da1c6840867239c5415cb5bceeb80164798ff627aac0a985'
            }

    _attributes = list(_cache_files.keys())


    _ext = '.json.gz'



    ## Cache constructor
    #
    # @param self The object pointer
    # @param inputPath The path to the folder that contains all the input/output files required
    # @param db Mode of storing objects ('file' or 'redis')
    def __init__(self, db='file', print_infos=False):


        self.store_mode = db
        rpCache._db_timeout = 10

        self.dirname = os_path.dirname(os_path.abspath( __file__ ))#+"/.."
        # input_cache
        self._input_cache_dir = self.dirname+'/input_cache/'
        # cache
        self._cache_dir = self.dirname+'/cache/'

        if self.store_mode!='file':
            self.redis = StrictRedis(host=self.store_mode, port=6379, db=0, decode_responses=True)
            if not wait_for_redis(self.redis, self._db_timeout):
                rpCache.logger.critical("Database "+self.store_mode+" is not reachable")
                rpCache.logger.info("Trying local redis...")
                self.redis = StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)
                if not wait_for_redis(self.redis, self._db_timeout):
                    rpCache.logger.critical("Database on localhost is not reachable")
                    rpCache.logger.info("Start local redis...")
                    p1 = Popen([redis_server.REDIS_SERVER_PATH], stdout=PIPE)
                    self.redis = StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)
                    if not wait_for_redis(self.redis, self._db_timeout):
                        rpCache.logger.critical("Database on localhost is not reachable")
                        exit()
            self.deprecatedMNXM_mnxm = CRedisDict('deprecatedMNXM_mnxm', self.redis)
            self.deprecatedMNXR_mnxr = CRedisDict('deprecatedMNXR_mnxr', self.redis)
            self.mnxm_strc = CRedisDict('mnxm_strc', self.redis)
            self.chemXref = CRedisDict('chemXref', self.redis)
            self.rr_reactions = CRedisDict('rr_reactions', self.redis)
            self.chebi_mnxm = CRedisDict('chebi_mnxm', self.redis)
            # rpReader attributes
            self.inchikey_mnxm = CRedisDict('inchikey_mnxm', self.redis)
            self.compXref = CRedisDict('compXref', self.redis)
            self.name_compXref = CRedisDict('name_compXref', self.redis)
            # rpCofactors attributes
            self.full_reactions = CRedisDict('full_reactions', self.redis)
        else:
            self.deprecatedMNXM_mnxm = None
            self.deprecatedMNXR_mnxr = None
            self.mnxm_strc = None
            self.chemXref = None
            self.rr_reactions = None
            self.chebi_mnxm = None
            # rpReader attributes
            self.inchikey_mnxm = None
            self.compXref = None
            self.name_compXref = None
            # rpCofactors attributes
            self.full_reactions = None



        self.print = print_infos

        try:
            if self.store_mode=='file':
                self._check_or_load_cache_in_memory(self._cache_dir)
            else:
                self._check_or_load_cache_in_db(self._cache_dir)
        except FileNotFoundError:
            print_FAILED()
            try:
                rpCache._check_or_download_cache_to_disk(self._cache_dir)
                if self.store_mode=='file':
                    self._check_or_load_cache_in_memory(self._cache_dir)
                else:
                    self._check_or_load_cache_in_db(self._cache_dir)
            except (r_exceptions.RequestException,
                    r_exceptions.InvalidSchema,
                    r_exceptions.ConnectionError):
                print_FAILED()
                rpCache.generate_cache(rpCache._input_cache_url, self._cache_dir)
                if self.store_mode=='file':
                    self._check_or_load_cache_in_memory(self._cache_dir)
                else:
                    self._check_or_load_cache_in_db(self._cache_dir)


    #####################################################
    ################# ERROR functions ###################
    #####################################################

    ## Error function for the convertion of structures
    #
    class Error(Exception):
        pass


    ## Error function for the convertion of structures
    #
    class DepictionError(Error):
        def __init__(self, message):
            #self.expression = expression
            self.message = message

    #url = 'https://www.metanetx.org/cgi-bin/mnxget/mnxref/'
    #url = 'ftp://ftp.vital-it.ch/databases/metanetx/MNXref/3.2/'

    @staticmethod
    def _check_or_download_cache_to_disk(cache_dir):
        for attr in rpCache._attributes:
            filename = attr+rpCache._ext
            if os_path.isfile(cache_dir+filename) and sha512(Path(cache_dir+filename).read_bytes()).hexdigest()==rpCache._cache_files[attr]:
                print(filename+" already downloaded ", end = '', flush=True)
                print_OK()
            else:
                filename = attr+rpCache._ext
                print("Downloading "+filename+"...", end = '', flush=True)
                start_time = time.time()
                if not os_path.isdir(cache_dir):
                    os_mkdir(cache_dir)
                download(rpCache._cache_url+filename, cache_dir+filename)
                rpCache._cache_files[attr] = True
                end_time = time.time()
                print_OK(end_time-start_time)


    def _check_or_load_cache_in_memory(self, cache_dir):
        for attribute in rpCache._attributes:
            if not getattr(self, attribute):
                filename = attribute+rpCache._ext
                print("Loading "+filename+"...", end = '', flush=True)
                data = self._load_cache_from_file(cache_dir+filename)
                print_OK()
                setattr(self, attribute, data)
            else:
                print(attribute+" already loaded in memory...", end = '', flush=True)
                print_OK()

    def _check_or_load_cache_in_db(self, cache_dir):
        for attribute in rpCache._attributes:
            if not CRedisDict.exists(self.redis, attribute):
                filename = attribute+rpCache._ext
                print("Loading "+filename+"...", end = '', flush=True)
                data = self._load_cache_from_file(cache_dir+filename)
                print_OK()
                self._store_cache_to_db(attribute, data)
            else:
                print(attribute+" already loaded in db...", end = '', flush=True)
                print_OK()


    @staticmethod
    def generate_cache(url, outdir):

        if not os_path.isdir(outdir):
            os_mkdir(outdir)

        # FETCH INPUT_CACHE FILES
        input_dir = 'input-'+os_path.basename(os_path.normpath(outdir))+'/'
        for file in rpCache._input_cache_files.keys():
            rpCache._download_input_cache(url, file, input_dir)


        # GENERATE CACHE FILES AND STORE THEM TO DISK
        deprecatedMNXM_mnxm = None
        f_deprecatedMNXM_mnxm = 'deprecatedMNXM_mnxm'+rpCache._ext
        if not os_path.isfile(outdir+f_deprecatedMNXM_mnxm):
            print("Generating deprecatedMNXM_mnxm...", end = '', flush=True)
            deprecatedMNXM_mnxm = rpCache._m_deprecatedMNXM_mnxm(input_dir+'chem_xref.tsv')
            print_OK()
            print("Storing deprecatedMNXM_mnxm to file...", end = '', flush=True)
            rpCache._store_cache_to_file(deprecatedMNXM_mnxm, f_deprecatedMNXM_mnxm)
            print_OK()
        else:
            print("File "+f_deprecatedMNXM_mnxm+" already exists")

        mnxm_strc = None
        f_mnxm_strc = 'mnxm_strc'+rpCache._ext
        if not os_path.isfile(outdir+f_mnxm_strc):
            if not deprecatedMNXM_mnxm:
                print("Loading "+f_deprecatedMNXM_mnxm+"...", end = '', flush=True)
                deprecatedMNXM_mnxm = rpCache._load_cache_from_file(outdir+f_deprecatedMNXM_mnxm)
                print_OK()
            print("Generating mnxm_strc...", end = '', flush=True)
            mnxm_strc = rpCache._m_mnxm_strc(input_dir+'/rr_compounds.tsv', input_dir+'chem_prop.tsv', deprecatedMNXM_mnxm)
            print_OK()
            print("Storing mnxm_strc to file...", end = '', flush=True)
            rpCache._store_cache_to_file(mnxm_strc, f_mnxm_strc)
            print_OK()
        else:
            print("File "+f_mnxm_strc+" already exists")

        inchikey_mnxm = None
        f_inchikey_mnxm = 'inchikey_mnxm'+rpCache._ext
        if not os_path.isfile(outdir+f_inchikey_mnxm):
            if not mnxm_strc:
                print("Loading "+f_inchikey_mnxm+"...", end = '', flush=True)
                mnxm_strc = rpCache._load_cache_from_file(f_mnxm_strc)
                print_OK()
            print("Generating inchikey_mnxm...", end = '', flush=True)
            inchikey_mnxm = rpCache._m_inchikey_mnxm(mnxm_strc)
            print_OK()
            del mnxm_strc
            print("Storing inchikey_mnxm to file...", end = '', flush=True)
            rpCache._store_cache_to_file(inchikey_mnxm, f_inchikey_mnxm)
            print_OK()
        else:
            print("File "+f_inchikey_mnxm+" already exists")

        chemXref = None
        f_chemXref = 'chemXref'+rpCache._ext
        if not os_path.isfile(outdir+f_chemXref):
            if not deprecatedMNXM_mnxm:
                print("Loading "+f_deprecatedMNXM_mnxm+"...", end = '', flush=True)
                deprecatedMNXM_mnxm = rpCache._load_cache_from_file(f_deprecatedMNXM_mnxm)
                print_OK()
            print("Generating chemXref...", end = '', flush=True)
            chemXref = rpCache._m_chemXref(input_dir+'chem_xref.tsv', deprecatedMNXM_mnxm)
            print_OK()
            print("Storing chemXref to file...", end = '', flush=True)
            rpCache._store_cache_to_file(chemXref, f_chemXref)
            print_OK()
        else:
            print("File "+f_chemXref+" already exists")

        chebi_mnxm = None
        f_chebi_mnxm = 'chebi_mnxm'+rpCache._ext
        if not os_path.isfile(outdir+f_chebi_mnxm):
            print("Generating chebi_mnxm...", end = '', flush=True)
            chebi_mnxm = rpCache._m_chebi_mnxm(chemXref)
            print_OK()
            del chemXref
            print("Storing chebi_mnxm to file...", end = '', flush=True)
            rpCache._store_cache_to_file(chebi_mnxm, f_chebi_mnxm)
            del chebi_mnxm
            print_OK()
        else:
            print("File "+f_chebi_mnxm+" already exists")

        deprecatedMNXR_mnxr = None
        f_deprecatedMNXR_mnxr = 'deprecatedMNXR_mnxr'+rpCache._ext
        if not os_path.isfile(outdir+f_deprecatedMNXR_mnxr):
            print("Generating deprecatedMNXR_mnxr...", end = '', flush=True)
            deprecatedMNXR_mnxr = rpCache._m_deprecatedMNXR_mnxr(input_dir+'reac_xref.tsv')
            print_OK()
            print("Storing deprecatedMNXR_mnxr to file...", end = '', flush=True)
            rpCache._store_cache_to_file(deprecatedMNXR_mnxr, f_deprecatedMNXR_mnxr)
            print_OK()
        else:
            print("File "+f_deprecatedMNXR_mnxr+" already exists")

        rr_reactions = None
        f_rr_reactions = 'rr_reactions'+rpCache._ext
        if not os_path.isfile(outdir+f_rr_reactions):
            if not deprecatedMNXM_mnxm:
                print("Loading "+f_deprecatedMNXM_mnxm+"...", end = '', flush=True)
                deprecatedMNXM_mnxm = rpCache._load_cache_from_file(f_deprecatedMNXM_mnxm)
                print_OK()
            if not deprecatedMNXR_mnxr:
                print("Loading "+f_deprecatedMNXR_mnxr+"...", end = '', flush=True)
                deprecatedMNXR_mnxr = rpCache._load_cache_from_file(f_deprecatedMNXR_mnxr)
                print_OK()
            print("Generating rr_reactions...", end = '', flush=True)
            rr_reactions = rpCache._m_rr_reactions(input_dir+'rules_rall.tsv', deprecatedMNXM_mnxm, deprecatedMNXR_mnxr)
            print_OK()
            del deprecatedMNXR_mnxr
            print("Storing rr_reactions to file...", end = '', flush=True)
            rpCache._store_cache_to_file(rr_reactions, f_rr_reactions)
            print_OK()
            del rr_reactions
        else:
            print("File "+f_rr_reactions+" already exists")

        compXref = name_compXref = None
        f_compXref = 'compXref'+rpCache._ext
        f_name_compXref = 'name_compXref'+rpCache._ext
        if not os_path.isfile(outdir+f_compXref) or not os_path.isfile(outdir+f_name_compXref):
            print("Generating compXref,name_compXref...", end = '', flush=True)
            compXref,name_compXref = rpCache._m_compXref(input_dir+'comp_xref.tsv')
            print_OK()
            print("Storing compXref to file...", end = '', flush=True)
            rpCache._store_cache_to_file(compXref, f_compXref)
            print_OK()
            del compXref
            print("Storing name_compXref to file...", end = '', flush=True)
            rpCache._store_cache_to_file(name_compXref, f_name_compXref)
            print_OK()
            del name_compXref
        else:
            print("Files "+f_compXref+", "+f_name_compXref+" already exist")

        full_reactions = None
        f_full_reactions = 'full_reactions'+rpCache._ext
        if not os_path.isfile(outdir+f_full_reactions):
            print("Generating full_reactions...", end = '', flush=True)
            if not deprecatedMNXM_mnxm:
                print("Loading "+f_deprecatedMNXM_mnxm+"...", end = '', flush=True)
                deprecatedMNXM_mnxm = rpCache._load_cache_from_file(f_deprecatedMNXM_mnxm)
                print_OK()
            if not deprecatedMNXR_mnxr:
                print("Loading "+f_deprecatedMNXR_mnxr+"...", end = '', flush=True)
                deprecatedMNXR_mnxr = rpCache._load_cache_from_file(f_deprecatedMNXR_mnxr)
                print_OK()
            full_reactions = rpCache._m_full_reactions(input_dir+'rxn_recipes.tsv', deprecatedMNXM_mnxm, deprecatedMNXR_mnxr)
            print_OK()
            print("Storing full_reactions to file...", end = '', flush=True)
            rpCache._store_cache_to_file(full_reactions, f_full_reactions)
            print_OK()
            del full_reactions
        else:
            print("File "+f_full_reactions+" already exists")


    @staticmethod
    def _download_input_cache(url, file, outdir):
        if not os_path.isdir(outdir):
            os_mkdir(outdir)
        filename = outdir+'/'+file
        if not os_path.isfile(filename):
            print("Downloading "+file+"...", end = '', flush=True)
            start_time = time.time()
            rpCache.__download_input_cache(url, file, outdir)
            end_time = time.time()
            print_OK(end_time-start_time)
        else:
            print(filename+" already downloaded ", end = '', flush=True)
            print_OK()

    @staticmethod
    def __download_input_cache(url, file, outdir):

        if not os_path.isdir(outdir):
            os_mkdir(outdir)


        # 3xCommon + rpReader
        if file in ['reac_xref.tsv', 'chem_xref.tsv', 'chem_prop.tsv', 'comp_xref.tsv']:
            urllib_request_urlretrieve(url+file, outdir+'/'+file)

        #TODO: need to add this file to the git or another location
        if file in ['rr_compounds.tsv', 'rxn_recipes.tsv']:
            urllib_request_urlretrieve('https://retrorules.org/dl/this/is/not/a/secret/path/rr02',
                                       outdir+'/rr02_more_data.tar.gz')
            tar = tarfile_open(outdir+'/rr02_more_data.tar.gz', 'r:gz')
            tar.extractall(outdir)
            tar.close()
            shutil_move(outdir+'/rr02_more_data/compounds.tsv',
                        outdir+'/rr_compounds.tsv')
            shutil_move(outdir+'/rr02_more_data/rxn_recipes.tsv',
                        outdir)
            os_rm(outdir+'/rr02_more_data.tar.gz')
            shutil_rmtree(outdir+'/rr02_more_data')

        if file=='rules_rall.tsv':
            urllib_request_urlretrieve('https://retrorules.org/dl/preparsed/rr02/rp3/hs',
                                       outdir+'/retrorules_rr02_rp3_hs.tar.gz')
            tar = tarfile_open(outdir+'/retrorules_rr02_rp3_hs.tar.gz', 'r:gz')
            tar.extractall(outdir)
            tar.close()
            shutil_move(outdir+'/retrorules_rr02_rp3_hs/retrorules_rr02_flat_all.tsv', outdir+'/rules_rall.tsv')
            os_rm(outdir+'/retrorules_rr02_rp3_hs.tar.gz')
            shutil_rmtree(outdir+'/retrorules_rr02_rp3_hs')




    ##########################################################
    ################## Private Functions #####################
    ##########################################################



    ## Method to load data from file
    #
    #  Load data from file
    #
    #  @param self Object pointer
    #  @param filename File to fetch data from
    #  @return file content
    @staticmethod
    def _load_cache_from_file(filename):
        if filename.endswith('.gz') or filename.endswith('.zip'):
            fp = gzip_open(filename, 'rt', encoding='ascii')
        else:
            fp = open(filename, 'r')
        return json_load(fp)

    ## Method to store data into file
    #
    # Store data into file as json (to store dictionnary structure)
    #
    #  @param self Object pointer
    #  @param data Data to write into file
    #  @param filename File to write data into
    @staticmethod
    def _store_cache_to_file(data, filename):
        if filename.endswith('.gz') or filename.endswith('.zip'):
            fp = gzip_open(filename, 'wt', encoding='ascii')
        else:
            fp = open(filename, 'w')
        json_dump(data, fp)

    ## Method to store data into redis database
    #
    #  Assign a CRedisDict object to the attribute to copy data into the database
    #
    #  @param self Object pointer
    #  @param attr_name Attribute name (database key)
    #  @param data Content of the attribute
    def _store_cache_to_db(self, attr_name, data):
        print("Storing "+attr_name+" to db...", end = '', flush=True)
        setattr(rpCache, attr_name, CRedisDict(attr_name, self.redis, data))
        print_OK()



    ## Function to create a dictionnary of old to new chemical id's
    #
    #  Generate a one-to-one dictionnary of old id's to new ones. Private function
    #
    # TODO: check other things about the mnxm emtry like if it has the right structure etc...
    @staticmethod
    def _checkMNXMdeprecated(mnxm, deprecatedMNXM_mnxm):
        try:
            return deprecatedMNXM_mnxm[mnxm]
        except (KeyError, TypeError):
            return mnxm


    ## Function to create a dictionnary of old to new reaction id's
    #
    # TODO: check other things about the mnxm emtry like if it has the right structure etc...
    @staticmethod
    def _checkMNXRdeprecated(mnxr, deprecatedMNXR_mnxr):
        try:
            return deprecatedMNXR_mnxr[mnxr]
        except (KeyError, TypeError):
            return mnxr


    #################################################################
    ################## Public functions #############################
    #################################################################


    ## Function to parse the chem_xref.tsv file of MetanetX
    #
    #  Generate a dictionnary of old to new MetanetX identifiers to make sure that we always use the freshest id's.
    # This can include more than one old id per new one and thus returns a dictionnary. Private function
    #
    #  @param self Object pointer
    #  @param chem_xref_path Input file path
    #  @return Dictionnary of identifiers
    #TODO: save the self.deprecatedMNXM_mnxm to be used in case there rp_paths uses an old version of MNX
    @staticmethod
    def _deprecatedMNX(xref_path):
        deprecatedMNX_mnx = {}
        with open(xref_path) as f:
            c = csv_reader(f, delimiter='\t')
            for row in c:
                if not row[0][0]=='#':
                    mnx = row[0].split(':')
                    if mnx[0]=='deprecated':
                        deprecatedMNX_mnx[mnx[1]] = row[1]
        return deprecatedMNX_mnx

    @staticmethod
    def _m_deprecatedMNXM_mnxm(chem_xref_path):
        deprecatedMNXM_mnxm = {}
        deprecatedMNXM_mnxm = rpCache._deprecatedMNX(chem_xref_path)
        deprecatedMNXM_mnxm.update(rpCache._convertMNXM)
        deprecatedMNXM_mnxm['MNXM01'] = 'MNXM1'
        return deprecatedMNXM_mnxm

    ## Function to parse the reac_xref.tsv file of MetanetX
    #
    #  Generate a dictionnary of old to new MetanetX identifiers to make sure that we always use the freshest id's.
    # This can include more than one old id per new one and thus returns a dictionnary. Private function
    #
    #  @param self Object pointer
    #  @param reac_xref_path Input file path
    #  @return Dictionnary of identifiers
    @staticmethod
    def _m_deprecatedMNXR_mnxr(reac_xref_path):
        return rpCache._deprecatedMNX(reac_xref_path)


    ## Convert chemical depiction to others type of depictions
    #
    # Usage example:
    # - convert_depiction(idepic='CCO', otype={'inchi', 'smiles', 'inchikey'})
    # - convert_depiction(idepic='InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3', itype='inchi', otype={'inchi', 'smiles', 'inchikey'})
    #  @param self The object pointer
    #  @param idepic String depiction to be converted, str
    #  @param itype type of depiction provided as input, str
    #  @param otype types of depiction to be generated, {"", "", ..}
    #  @return odepic generated depictions, {"otype1": "odepic1", ..}
    @staticmethod
    def _convert_depiction(idepic, itype='smiles', otype={'inchikey'}):
        # Import (if needed)
        if itype == 'smiles':
            rdmol = MolFromSmiles(idepic, sanitize=True)
        elif itype == 'inchi':
            rdmol = MolFromInchi(idepic, sanitize=True)
        else:
            raise NotImplementedError('"{}" is not a valid input type'.format(itype))
        if rdmol is None:  # Check imprt
            raise rpCache.DepictionError('Import error from depiction "{}" of type "{}"'.format(idepic, itype))
        # Export
        odepic = dict()
        for item in otype:
            if item == 'smiles':
                odepic[item] = MolToSmiles(rdmol)  # MolToSmiles is tricky, one mays want to check the possible options..
            elif item == 'inchi':
                odepic[item] = MolToInchi(rdmol)
            elif item == 'inchikey':
                odepic[item] = MolToInchiKey(rdmol)
            else:
                raise NotImplementedError('"{}" is not a valid output type'.format(otype))
        return odepic


    ## Function to parse the chemp_prop.tsv file from MetanetX and compounds.tsv from RetroRules. Uses the InchIkey as key to the dictionnary
    #
    #  Generate a dictionnary gaving the formula, smiles, inchi and inchikey for the components
    #
    #  @param self Object pointer
    #  @param chem_prop_path Input file path
    #  @return mnxm_strc Dictionnary of formula, smiles, inchi and inchikey
    @staticmethod
    def _m_mnxm_strc(rr_compounds_path, chem_prop_path, deprecatedMNXM_mnxm):
        mnxm_strc = {}
        for row in csv_DictReader(open(rr_compounds_path), delimiter='\t'):
            tmp = {'formula':  None,
                    'smiles': None,
                    'inchi': row['inchi'],
                    'inchikey': None,
                    'mnxm': rpCache._checkMNXMdeprecated(row['cid'], deprecatedMNXM_mnxm),
                    'name': None}
            try:
                resConv = rpCache._convert_depiction(idepic=tmp['inchi'], itype='inchi', otype={'smiles','inchikey'})
                for i in resConv:
                    tmp[i] = resConv[i]
            except rpCache.DepictionError as e:
                rpCache.logger.warning('Could not convert some of the structures: '+str(tmp))
                rpCache.logger.warning(e)
            mnxm_strc[tmp['mnxm']] = tmp
        with open(chem_prop_path) as f:
            c = csv_reader(f, delimiter='\t')
            for row in c:
                if not row[0][0]=='#':
                    mnxm = rpCache._checkMNXMdeprecated(row[0], deprecatedMNXM_mnxm)
                    tmp = {'formula':  row[2],
                            'smiles': row[6],
                            'inchi': row[5],
                            'inchikey': row[8],
                            'mnxm': mnxm,
                            'name': row[1]}
                    for i in tmp:
                        if tmp[i]=='' or tmp[i]=='NA':
                            tmp[i] = None
                    if mnxm in mnxm_strc:
                        mnxm_strc[mnxm]['formula'] = row[2]
                        mnxm_strc[mnxm]['name'] = row[1]
                        if not mnxm_strc[mnxm]['smiles'] and tmp['smiles']:
                            mnxm_strc[mnxm]['smiles'] = tmp['smiles']
                        if not mnxm_strc[mnxm]['inchikey'] and tmp['inchikey']:
                            mnxm_strc[mnxm]['inchikey'] = tmp['inchikey']
                    else:
                        #check to see if the inchikey is valid or not
                        otype = set({})
                        if not tmp['inchikey']:
                            otype.add('inchikey')
                        if not tmp['smiles']:
                            otype.add('smiles')
                        if not tmp['inchi']:
                            otype.add('inchi')
                        itype = ''
                        if tmp['inchi']:
                            itype = 'inchi'
                        elif tmp['smiles']:
                            itype = 'smiles'
                        else:
                            rpCache.logger.warning('No valid entry for the convert_depiction function')
                            continue
                        try:
                            resConv = rpCache._convert_depiction(idepic=tmp[itype], itype=itype, otype=otype)
                            for i in resConv:
                                tmp[i] = resConv[i]
                        except rpCache.DepictionError as e:
                            rpCache.logger.warning('Could not convert some of the structures: '+str(tmp))
                            rpCache.logger.warning(e)
                        mnxm_strc[tmp['mnxm']] = tmp
        return mnxm_strc


    ## Function to parse the chem_xref.tsv file of MetanetX
    #
    #  Generate a dictionnary of all cross references for a given chemical id (MNX) to other database id's
    #
    #  @param self Object pointer
    #  @param chem_xref_path Input file path
    #  @return a The dictionnary of identifiers
    #TODO: save the self.deprecatedMNXM_mnxm to be used in case there rp_paths uses an old version of MNX
    @staticmethod
    def _m_chemXref(chem_xref_path, deprecatedMNXM_mnxm):
        chemXref = {}
        with open(chem_xref_path) as f:
            c = csv_reader(f, delimiter='\t')
            for row in c:
                if not row[0][0]=='#':
                    mnx = rpCache._checkMNXMdeprecated(row[1], deprecatedMNXM_mnxm)
                    if len(row[0].split(':'))==1:
                        dbName = 'mnx'
                        dbId = row[0]
                    else:
                        dbName = row[0].split(':')[0]
                        dbId = ''.join(row[0].split(':')[1:])
                        if dbName=='deprecated':
                            dbName = 'mnx'
                    #mnx
                    if not mnx in chemXref:
                        chemXref[mnx] = {}
                    if not dbName in chemXref[mnx]:
                        chemXref[mnx][dbName] = []
                    if not dbId in chemXref[mnx][dbName]:
                        chemXref[mnx][dbName].append(dbId)
                    ### DB ###
                    if not dbName in chemXref:
                        chemXref[dbName] = {}
                    if not dbId in chemXref[dbName]:
                        chemXref[dbName][dbId] = mnx
        return chemXref


    ## Function to parse the chem_xref.tsv file of MetanetX
    #
    #  Generate a dictionnary of all cross references for a given chemical id (MNX) to other database id's
    #
    #  @param self Object pointer
    #  @param chem_xref_path Input file path
    #  @return a The dictionnary of identifiers
    #TODO: save the self.deprecatedMNXM_mnxm to be used in case there rp_paths uses an old version of MNX
#    def _m_chebi_mnxm(self, chemXref):
    @staticmethod
    def _m_chebi_mnxm(chemXref):
        chebi_mnxm = {}
        for mnxm in chemXref:
            if 'chebi' in chemXref[mnxm]:
                for c in chemXref[mnxm]['chebi']:
                    chebi_mnxm[c] = mnxm
        return chebi_mnxm


    ## Function to parse the rules_rall.tsv from RetroRules
    #
    #  Extract from the reactions rules the ruleID, the reactionID, the direction of the rule directed to the origin reaction
    #
    #  @param self The object pointer.
    #  @param path The input file path.
    #  @return rule Dictionnary describing each reaction rule
    @staticmethod
    def _m_rr_reactions(rules_rall_path, deprecatedMNXM_mnxm, deprecatedMNXR_mnxr):
        rr_reactions = {}
        try:
            #with open(rules_rall_path, 'r') as f:
            #    reader = csv.reader(f, delimiter = '\t')
            #    next(reader)
            #    rule = {}
            #    for row in reader:
            for row in csv_DictReader(open(rules_rall_path), delimiter='\t'):
                #NOTE: as of now all the rules are generated using MNX
                #but it may be that other db are used, we are handling this case
                #WARNING: can have multiple products so need to seperate them
                products = {}
                for i in row['Product_IDs'].split('.'):
                    mnxm = rpCache._checkMNXMdeprecated(i, deprecatedMNXM_mnxm)
                    if not mnxm in products:
                        products[mnxm] = 1
                    else:
                        products[mnxm] += 1
                try:
                    #WARNING: one reaction rule can have multiple reactions associated with them
                    #To change when you can set subpaths from the mutliple numbers of
                    #we assume that the reaction rule has multiple unique reactions associated
                    if row['# Rule_ID'] not in rr_reactions:
                        rr_reactions[row['# Rule_ID']] = {}
                    if row['# Rule_ID'] in rr_reactions[row['# Rule_ID']]:
                        rpCache.logger.warning('There is already reaction '+str(row['# Rule_ID'])+' in reaction rule '+str(row['# Rule_ID']))
                    rr_reactions[row['# Rule_ID']][row['Reaction_ID']] = {
                        'rule_id': row['# Rule_ID'],
                        'rule_score': float(row['Score_normalized']),
                        'reac_id': rpCache._checkMNXRdeprecated(row['Reaction_ID'], deprecatedMNXR_mnxr),
                        'subs_id': rpCache._checkMNXMdeprecated(row['Substrate_ID'], deprecatedMNXM_mnxm),
                        'rel_direction': int(row['Rule_relative_direction']),
                        'left': {rpCache._checkMNXMdeprecated(row['Substrate_ID'], deprecatedMNXM_mnxm): 1},
                        'right': products}
                except ValueError:
                    rpCache.logger.error('Problem converting rel_direction: '+str(row['Rule_relative_direction']))
                    rpCache.logger.error('Problem converting rule_score: '+str(row['Score_normalized']))
            return rr_reactions
        except FileNotFoundError as e:
                rpCache.logger.error('Could not read the rules_rall file ('+str(rules_rall_path)+')')
                return {}


    @staticmethod
    def _m_inchikey_mnxm(mnxm_strc):
        inchikey_mnxm = {}
        for mnxm in mnxm_strc:
            inchikey = mnxm_strc[mnxm]['inchikey']
            if not inchikey: inchikey = 'NO_INCHIKEY'
            if not inchikey in inchikey_mnxm:
                inchikey_mnxm[inchikey] = []
            inchikey_mnxm[inchikey].append(mnxm)
        return inchikey_mnxm

    # rpReader
    ## Function to parse the compXref.tsv file of MetanetX
    #
    #  Generate a dictionnary of compartments id's (MNX) to other database id's
    #
    #  @param self Object pointer
    #  @param chem_xref_path Input file path
    #  @return a The dictionnary of identifiers
    #TODO: save the self.deprecatedMNXM_mnxm to be used in case there rp_paths uses an old version of MNX
    @staticmethod
    def _m_compXref(compXref_path):
        compXref = {}
        name_compXref = {}
        try:
            with open(compXref_path) as f:
                c = csv_reader(f, delimiter='\t')
                #not_recognised = []
                for row in c:
                    #cid = row[0].split(':')
                    if not row[0][0]=='#':
                        #collect the info
                        mnxc = row[1]
                        if len(row[0].split(':'))==1:
                            dbName = 'mnx'
                            dbCompId = row[0]
                        else:
                            dbName = row[0].split(':')[0]
                            dbCompId = ''.join(row[0].split(':')[1:])
                            dbCompId = dbCompId.lower()
                        if dbName=='deprecated':
                            dbName = 'mnx'
                        #create the dicts
                        if not mnxc in compXref:
                            compXref[mnxc] = {}
                        if not dbName in compXref[mnxc]:
                            compXref[mnxc][dbName] = []
                        if not dbCompId in compXref[mnxc][dbName]:
                            compXref[mnxc][dbName].append(dbCompId)
                        #create the reverse dict
                        if not dbCompId in name_compXref:
                            name_compXref[dbCompId] = mnxc
        except FileNotFoundError:
            rpCache.logger.error('compXref file not found')
            return {}
        return compXref,name_compXref


    ## Generate complete reactions from the rxn_recipes.tsv from RetroRules
    #
    #  These are the compplete reactions from which the reaction rules are generated from. This is used to
    # reconstruct the full reactions from monocomponent reactions
    #
    #  @param self The pointer object
    #  @param rxn_recipes_path Path to the recipes file
    #  @return Boolean that determines the success or failure of the function
    @staticmethod
    def _m_full_reactions(rxn_recipes_path, deprecatedMNXM_mnxm, deprecatedMNXR_mnxr):
        #### for character matching that are returned
        DEFAULT_STOICHIO_RESCUE = {"4n": 4, "3n": 3, "2n": 2, 'n': 1,
                           '(n)': 1, '(N)': 1, '(2n)': 2, '(x)': 1,
                           'N': 1, 'm': 1, 'q': 1,
                           '0.01': 1, '0.1': 1, '0.5': 1, '1.5': 1,
                           '0.02': 1, '0.2': 1,
                           '(n-1)': 0, '(n-2)': -1}
        reaction = {}
        try:
            for row in csv_DictReader(open(rxn_recipes_path), delimiter='\t'):
                tmp = {} # makes sure that if theres an error its not added
                #parse the reaction equation
                if not len(row['Equation'].split('='))==2:
                    rpCache.logger.warning('There should never be more or less than a left and right of an equation')
                    rpCache.logger.warnin(row['Equation'])
                    continue
                ######### LEFT ######
                #### MNX id
                tmp['left'] = {}
                # if row['#Reaction_ID']=="MNXR141948":
                #     print(row)
                #     exit()
                for spe in re_findall(r'(\(n-1\)|\d+|4n|3n|2n|n|\(n\)|\(N\)|\(2n\)|\(x\)|N|m|q|\(n\-2\)|\d+\.\d+) ([\w\d]+)@\w+', row['Equation'].split('=')[0]):
                    #1) try to rescue if its one of the values
                    try:
                        tmp['left'][rpCache._checkMNXMdeprecated(spe[1], deprecatedMNXM_mnxm)] = DEFAULT_STOICHIO_RESCUE[spe[0]]
                    except KeyError:
                        #2) try to convert to int if its not
                        try:
                            tmp['left'][rpCache._checkMNXMdeprecated(spe[1], deprecatedMNXM_mnxm)] = int(spe[0])
                        except ValueError:
                            rpCache.logger.warning('Cannot convert '+str(spe[0]))
                            continue
                ####### RIGHT #####
                ####  MNX id
                tmp['right'] = {}
                for spe in re_findall(r'(\(n-1\)|\d+|4n|3n|2n|n|\(n\)|\(N\)|\(2n\)|\(x\)|N|m|q|\(n\-2\)|\d+\.\d+) ([\w\d]+)@\w+', row['Equation'].split('=')[1]):
                    #1) try to rescue if its one of the values
                    try:
                        tmp['right'][rpCache._checkMNXMdeprecated(spe[1], deprecatedMNXM_mnxm)] = DEFAULT_STOICHIO_RESCUE[spe[0]]
                    except KeyError:
                        #2) try to convert to int if its not
                        try:
                            tmp['right'][rpCache._checkMNXMdeprecated(spe[1], deprecatedMNXM_mnxm)] = int(spe[0])
                        except ValueError:
                            rpCache.logger.warning('Cannot convert '+str(spe[0]))
                            continue
                ####### DIRECTION ######
                try:
                    tmp['direction'] = int(row['Direction'])
                except ValueError:
                    rpCache.logger.error('Cannot convert '+str(row['Direction'])+' to int')
                    continue
                ### add the others
                tmp['main_left'] = row['Main_left'].split(',')
                tmp['main_right'] = row['Main_right'].split(',')
                reaction[rpCache._checkMNXRdeprecated(row['#Reaction_ID'], deprecatedMNXR_mnxr)] = tmp
            return reaction
        except FileNotFoundError:
            rpCache.logger.error('Cannot find file: '+str(rxn_recipes_path))
            return False
