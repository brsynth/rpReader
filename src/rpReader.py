import csv
# import os
from itertools import product as itertools_product
# import pickle
# import gzip
# from rdkit.Chem import MolFromSmiles, MolFromInchi, MolToSmiles, MolToInchi, MolToInchiKey, AddHs
import sys
import argparse
# import random
# #import json
# import copy
# #from .setup_self.logger import self.logger
import logging
# import io
# import re
# #import tarfile

import rpSBML
from rpCache import rpCache

## @package rpReader
#
# Collectoion of functions that convert the outputs from various sources to the SBML format (rpSBML) for further analyses

## Class to read all the input files
#
# Contains all the functions that read the cache files and input files to reconstruct the heterologous pathways
class rpReader(rpCache):
    ## InputReader constructor
    #
    #  @param self The object pointer
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.logger.info('Starting instance of rpReader')

    #######################################################################
    ############################# PRIVATE FUNCTIONS #######################
    #######################################################################



    ###############################################################
    ############################ RP2paths entry functions #########
    ###############################################################

    ## Function to group all the functions for parsing RP2 output to SBML files
    #
    # Takes RP2paths's compounds.txt and out_paths.csv and RetroPaths's *_scope.csv files and generates SBML
    #
    # @param compounds string path to RP2paths out_paths file
    # @param scope string path to RetroPaths2's scope file output
    # @param outPaths string path to RP2paths out_paths file
    # @param maxRuleIds int The maximal number of members in a single substep (Reaction Rule)
    # @param compartment_id string The ID of the SBML's model compartment where to add the reactions to
    # @return Boolean The success or failure of the function
    def rp2ToSBML(self,
                  rp2paths_compounds,
                  rp2_pathways,
                  rp2paths_pathways,
                  tmpOutputFolder=None,
                  upper_flux_bound=999999,
                  lower_flux_bound=0,
                  maxRuleIds=10,
                  pathway_id='rp_pathway',
                  compartment_id='MNXC3',
                  species_group_id='central_species'):
        rp_strc = self._compounds(rp2paths_compounds)
        rp_transformation = self._transformation(rp2_pathways)
        return self._outPathsToSBML(rp_strc,
                                    rp_transformation,
                                    rp2paths_pathways,
                                    upper_flux_bound,
                                    lower_flux_bound,
                                    tmpOutputFolder,
                                    maxRuleIds,
                                    pathway_id,
                                    compartment_id,
                                    species_group_id)

    ## Function to parse the compounds.txt file
    #
    #  Extract the smile and the structure of each compounds of RP2Path output
    #  Method to parse all the RP output compounds.
    #
    #  @param self Object pointer
    #  @param path The compounds.txt file path
    #  @return rp_compounds Dictionnary of smile and structure for each compound
    def _compounds(self, path):
        #self.rp_strc = {}
        rp_strc = {}
        try:
            #### we might pass binary in the REST version
            if isinstance(path, bytes):
                reader = csv.reader(io.StringIO(path.decode('utf-8')), delimiter='\t')
            else:
                reader = csv.reader(open(path, 'r', encoding='utf-8'), delimiter='\t')
            next(reader)
            for row in reader:
                rp_strc[row[0]] = {'smiles': row[1]}  #, 'structure':row[1].replace('[','').replace(']','')
                try:
                    rp_strc[row[0]]['inchi'] = self.mnxm_strc[row[0]]['inchi']
                except KeyError:
                    #try to generate them yourself by converting them directly
                    try:
                        resConv = self._convert_depiction(idepic=row[1], itype='smiles', otype={'inchi'})
                        rp_strc[row[0]]['inchi'] = resConv['inchi']
                    except NotImplementedError as e:
                        self.logger.warning('Could not convert the following SMILES to InChI: '+str(row[1]))
                try:
                    rp_strc[row[0]]['inchikey'] = self.mnxm_strc[row[0]]['inchikey']
                    #try to generate them yourself by converting them directly
                    #TODO: consider using the inchi writing instead of the SMILES notation to find the inchikey
                except KeyError:
                    try:
                        resConv = self._convert_depiction(idepic=row[1], itype='smiles', otype={'inchikey'})
                        rp_strc[row[0]]['inchikey'] = resConv['inchikey']
                    except NotImplementedError as e:
                        self.logger.warning('Could not convert the following SMILES to InChI key: '+str(row[1]))
        except (TypeError, FileNotFoundError) as e:
            self.logger.error('Could not read the compounds file ('+str(path)+')')
            raise RuntimeError
        return rp_strc


    ## Function to parse the scope.csv file
    #
    #  Extract the reaction rules from the retroPath2.0 output using the scope.csv file
    #
    #  @param self Object pointer
    #  @param path The scope.csv file path
    def _transformation(self, path):
        rp_transformation = {}
        #### we might pass binary in the REST version
        reader = None
        if isinstance(path, bytes):
            reader = csv.reader(io.StringIO(path.decode('utf-8')), delimiter=',')
        else:
            try:
                reader = csv.reader(open(path, 'r'), delimiter=',')
            except FileNotFoundError:
                self.logger.error('Could not read the compounds file: '+str(path))
                return {}
        next(reader)
        for row in reader:
            if not row[1] in rp_transformation:
                rp_transformation[row[1]] = {}
                rp_transformation[row[1]]['rule'] = row[2]
                rp_transformation[row[1]]['ec'] = [i.replace(' ', '') for i in row[11][1:-1].split(',') if not i.replace(' ', '')=='NOEC']
        return rp_transformation


    #TODO: make sure that you account for the fact that each reaction may have multiple associated reactions
    ## Function to parse the out_paths.csv file
    #
    #  Reading the RP2path output and extract all the information for each pathway
    #  RP2path Metabolic pathways from out_paths.csv
    #  create all the different values for heterologous paths from the RP2path out_paths.csv file
    #  Note that path_step are in reverse order here
    #
    #  @param self Object pointer
    #  @param path The out_path.csv file path
    #  @maxRuleId maximal numer of rules associated with a step
    #  @return toRet_rp_paths Pathway object
    def _outPathsToSBML(self,
            rp_strc,
            rp_transformation,
            rp2paths_outPath,
            upper_flux_bound=999999,
            lower_flux_bound=0,
            tmpOutputFolder=None,
            maxRuleIds=10,
            pathway_id='rp_pathway',
            compartment_id='MNXC3',
            species_group_id='central_species'):
        #try:
        rp_paths = {}
        #reactions = self.rr_reactionsingleRule.split('__')[1]s
        #with open(path, 'r') as f:
        #### we might pass binary in the REST version
        if isinstance(rp2paths_outPath, bytes):
            reader = csv.reader(io.StringIO(rp2paths_outPath.decode('utf-8')))
        else:
            reader = csv.reader(open(rp2paths_outPath, 'r'))
        next(reader)
        current_path_id = 0
        path_step = 1
        for row in reader:
            try:
                if not int(row[0])==current_path_id:
                    path_step = 1
                else:
                    path_step += 1
                #important to leave them in order
                current_path_id = int(row[0])
            except ValueError:
                self.logger.error('Cannot convert path_id to int ('+str(row[0])+')')
                #return {}
                return False
            #################################
            ruleIds = row[2].split(',')
            if ruleIds==None:
                self.logger.error('The rulesIds is None')
                #pass # or continue
                continue
            ###WARNING: This is the part where we select some rules over others
            # we do it by sorting the list according to their score and taking the topx
            tmp_rr_reactions = {}
            for r_id in ruleIds:
                for rea_id in self.rr_reactions[r_id]:
                    tmp_rr_reactions[str(r_id)+'__'+str(rea_id)] = self.rr_reactions[r_id][rea_id]
            if len(ruleIds)>int(maxRuleIds):
                self.logger.warning('There are too many rules, limiting the number to random top '+str(maxRuleIds))
                try:
                    ruleIds = [y for y,_ in sorted([(i, tmp_rr_reactions[i]['rule_score']) for i in tmp_rr_reactions])][:int(maxRuleIds)]
                except KeyError:
                    self.logger.warning('Could not select topX due inconsistencies between rules ids and rr_reactions... selecting random instead')
                    ruleIds = random.sample(tmp_rr_reactions, int(maxRuleIds))
            else:
                ruleIds = tmp_rr_reactions
            sub_path_step = 1
            for singleRule in ruleIds:
                tmpReac = {'rule_id': singleRule.split('__')[0],
                        'rule_ori_reac': {'mnxr': singleRule.split('__')[1]},
                        'rule_score': self.rr_reactions[singleRule.split('__')[0]][singleRule.split('__')[1]]['rule_score'],
                        'right': {},
                        'left': {},
                        'path_id': int(row[0]),
                        'step': path_step,
                        'transformation_id': row[1][:-2]}
                ############ LEFT ##############
                for l in row[3].split(':'):
                    tmp_l = l.split('.')
                    try:
                        #tmpReac['left'].append({'stoichio': int(tmp_l[0]), 'name': tmp_l[1]})
                        mnxm = '' #TODO: change this
                        if tmp_l[1] in self.deprecatedMNXM_mnxm:
                            mnxm = self.deprecatedMNXM_mnxm[tmp_l[1]]
                        else:
                            mnxm = tmp_l[1]
                        tmpReac['left'][mnxm] = int(tmp_l[0])
                    except ValueError:
                        self.logger.error('Cannot convert tmp_l[0] to int ('+str(tmp_l[0])+')')
                        #return {}
                        return False
                ############## RIGHT ###########
                for r in row[4].split(':'):
                    tmp_r = r.split('.')
                    try:
                        #tmpReac['right'].append({'stoichio': int(tmp_r[0]), 'name': tmp_r[1]})
                        mnxm = '' #TODO change this
                        if tmp_r[1] in self.deprecatedMNXM_mnxm:
                            mnxm = self.deprecatedMNXM_mnxm[tmp_r[1]]  #+':'+self.rr_reactions[tmpReac['rule_id']]['left']
                        else:
                            mnxm = tmp_r[1]  #+':'+self.rr_reactions[tmpReac['rule_id']]['left']
                        tmpReac['right'][mnxm] = int(tmp_r[0])
                    except ValueError:
                        self.logger.error('Cannot convert tmp_r[0] to int ('+str(tmp_r[0])+')')
                        return {}
                #################################
                if not int(row[0]) in rp_paths:
                    rp_paths[int(row[0])] = {}
                if not int(path_step) in rp_paths[int(row[0])]:
                    rp_paths[int(row[0])][int(path_step)] = {}
                rp_paths[int(row[0])][int(path_step)][int(sub_path_step)] = tmpReac
                sub_path_step += 1
        #### pathToSBML ####
        try:
            mnxc = self.name_compXref[compartment_id]
        except KeyError:
            self.logger.error('Could not Xref compartment_id ('+str(compartment_id)+')')
            return False
        #for pathNum in self.rp_paths:
        sbml_paths = {}
        for pathNum in rp_paths:
            #first level is the list of lists of sub_steps
            #second is itertools all possible combinations using product
            altPathNum = 1
            for comb_path in list(itertools_product(*[[(i,y) for y in rp_paths[pathNum][i]] for i in rp_paths[pathNum]])):
                steps = []
                for i, y in comb_path:
                    steps.append(rp_paths[pathNum][i][y])
                path_id = steps[0]['path_id']
                rpsbml = rpSBML.rpSBML('rp_'+str(path_id)+'_'+str(altPathNum))
                #1) create a generic Model, ie the structure and unit definitions that we will use the most
                ##### TODO: give the user more control over a generic model creation:
                #   -> special attention to the compartment
                rpsbml.genericModel('RetroPath_Pathway_'+str(path_id)+'_'+str(altPathNum),
                        'RP_model_'+str(path_id)+'_'+str(altPathNum),
                        self.compXref[mnxc],
                        compartment_id,
                        upper_flux_bound,
                        lower_flux_bound)
                #2) create the pathway (groups)
                rpsbml.createPathway(pathway_id)
                rpsbml.createPathway(species_group_id)
                #3) find all the unique species and add them to the model
                all_meta = set([i for step in steps for lr in ['left', 'right'] for i in step[lr]])
                for meta in all_meta:
                    try:
                        chemName = self.mnxm_strc[meta]['name']
                    except KeyError:
                        chemName = None
                    #compile as much info as you can
                    #xref
                    try:
                        spe_xref = self.chemXref[meta]
                    except KeyError:
                        spe_xref = {}
                    #inchi
                    try:
                        spe_inchi = rp_strc[meta]['inchi']
                    except KeyError:
                        spe_inchi = None
                    #inchikey
                    try:
                        spe_inchikey = rp_strc[meta]['inchikey']
                    except KeyError:
                        spe_inchikey = None
                    #smiles
                    try:
                        spe_smiles = rp_strc[meta]['smiles']
                    except KeyError:
                        spe_smiles = None
                    #pass the information to create the species
                    rpsbml.createSpecies(meta,
                            compartment_id,
                            chemName,
                            spe_xref,
                            spe_inchi,
                            spe_inchikey,
                            spe_smiles,
                            species_group_id)
                #4) add the complete reactions and their annotations
                for step in steps:
                    #add the substep to the model
                    step['sub_step'] = altPathNum
                    rpsbml.createReaction('RP'+str(step['step']), # parameter 'name' of the reaction deleted : 'RetroPath_Reaction_'+str(step['step']),
                            upper_flux_bound,
                            lower_flux_bound,
                            step,
                            compartment_id,
                            rp_transformation[step['transformation_id']]['rule'],
                            {'ec': rp_transformation[step['transformation_id']]['ec']},
                            pathway_id)
                #5) adding the consumption of the target
                targetStep = {'rule_id': None,
                        'left': {[i for i in all_meta if i[:6]=='TARGET'][0]: 1},
                        'right': [],
                        'step': None,
                        'sub_step': None,
                        'path_id': None,
                        'transformation_id': None,
                        'rule_score': None,
                        'rule_ori_reac': None}
                rpsbml.createReaction('RP1_sink',
                        upper_flux_bound,
                        lower_flux_bound,
                        targetStep,
                        compartment_id)
                #6) Add the flux objectives
                if tmpOutputFolder:
                    rpsbml.writeSBML(tmpOutputFolder)
                else:
                    sbml_paths['rp_'+str(step['path_id'])+'_'+str(altPathNum)] = rpsbml
                altPathNum += 1
        return sbml_paths


    #######################################################################
    ############################# JSON input ##############################
    #######################################################################


    #WARNING: we are not setting any restrictions on the number of steps allowed here and instead we
    #take the rule with the highest dimension. Also assume that there is a single rule at a maximal
    #dimension
    ## Function to generate an SBLM model from a JSON file
    #
    #  Read the json files of a folder describing pathways and generate an SBML file for each
    #  TODO: remove the default MNXC3 compartment ID
    #  TODO: change the ID of all species to take a normal string and not sepcial caracters
    #  WARNING: We are only using a single rule (technically with the highest diameter)
    #
    #  @param self Object pointer
    # @param colJson Dictionnary of
    #  @return rpsbml.document the SBML document
    #TODO: update this to include _hdd parsing
    def jsonToSBML(self,
                   collJson,
                   upper_flux_bound=999999,
                   lower_flux_bound=0,
                   pathway_id='rp_pathway',
                   compartment_id='MNXC3',
                   species_group_id='central_species'):
        #global parameters used for all parameters
        pathNum = 1
        rp_paths = {}
        reac_smiles = {}
        reac_ecs = {}
        species_list = {}
        reactions_list = {}
        source_cid = {}
        source_stochio = {}
        cid_inchikey = {}
        sink_species = {}
        ############################################
        ############## gather the data #############
        ############################################
        for json_dict in collJson:
            ########### construct rp_paths ########
            reac_smiles[pathNum] = {}
            reac_ecs[pathNum] = {}
            species_list[pathNum] = {}
            reactions_list[pathNum] = {}
            cid_inchikey[pathNum] = {}
            sink_species[pathNum] = {}
            stochio = {}
            inchikey_cid = {}
            source_species = []
            skip_pathway = False
            for node in collJson[json_dict]['elements']['nodes']:
                ##### compounds ####
                if node['data']['type']=='compound':
                    cid_inchikey[pathNum][node['data']['id'].replace('-', '')] = node['data']['id']
                    species_list[pathNum][node['data']['id'].replace('-', '')] = {'inchi': node['data']['InChI'],
                                    'inchikey': node['data']['id'],
                                    'smiles': node['data']['SMILES']}
                    if int(node['data']['isSource'])==1:
                        #TODO: there should always be only one source, to check
                        source_species.append(node['data']['id'].replace('-', ''))
                        source_cid[pathNum] = node['data']['id'].replace('-', '')
                    if int(node['data']['inSink'])==1:
                        sink_species[pathNum][node['data']['id'].replace('-', '')] = node['data']['id']
                ###### reactions ######
                elif node['data']['type']=='reaction':
                    #NOTE: pick the rule with the highest diameter
                    r_id = sorted(node['data']['Rule ID'], key=lambda x: int(x.split('-')[-2]), reverse=True)[0]
                    reactions_list[pathNum][node['data']['id']] = {'rule_id': r_id,
                        'rule_ori_reac': None,
                        'right': {},
                        'left': {},
                        'path_id': pathNum,
                        'step': None,
                        'sub_step': None,
                        'transformation_id': None,
                        'rule_score': node['data']['Score']}
                    reac_smiles[pathNum][r_id] = node['data']['Reaction SMILES']
                    reac_ecs[pathNum][r_id] = list(filter(None, [i for i in node['data']['EC number']]))
                    stochio[node['data']['id']] = {}
                    for i in node['data']['Stoechiometry']:
                        stochio[node['data']['id']][i.replace('-', '')] = node['data']['Stoechiometry'][i]
            ############ make main pathway ###########
            main_reac = {}
            for reaction_node in collJson[json_dict]['elements']['edges']:
                if not len(reaction_node['data']['source'].split('-'))==3:
                    if not reaction_node['data']['source'] in reactions_list[pathNum]:
                        self.logger.error('The following reaction was not found in the JSON elements: '+str(reaction_node['data']['source']))
                        skip_pathway = True
                        break
                    else:
                        rid = reaction_node['data']['source']
                        try:
                            cid = inchikey_cid[reaction_node['data']['target'].replace('-', '')]
                        except KeyError:
                            cid = reaction_node['data']['target'].replace('-', '')
                        try:
                            reactions_list[pathNum][rid]['left'][cid] = stochio[rid][cid]
                        except KeyError:
                            reactions_list[pathNum][rid]['left'][cid] = 1.0
                            self.logger.warning('The cid ('+str(cid)+') has not been detected by stochio. Setting to 1.0')
                if not len(reaction_node['data']['target'].split('-'))==3:
                    if not reaction_node['data']['target'] in reactions_list[pathNum]:
                        self.logger.error('The following reaction was not found in the JSON elements: '+str(reaction_node['data']['source']))
                        skip_pathway = True
                        break
                    else:
                        rid = reaction_node['data']['target']
                        try:
                            cid = inchikey_cid[reaction_node['data']['source'].replace('-', '')]
                        except KeyError:
                            cid = reaction_node['data']['source'].replace('-', '')
                        try:
                            reactions_list[pathNum][rid]['right'][cid] = stochio[rid][cid]
                        except KeyError:
                            reactions_list[pathNum][rid]['right'][cid] = 1.0
                            self.logger.warning('The cid ('+str(cid)+') has not been detected by stochio. Setting to 1.0')
            ################# calculate the steps associated with the reactions_list ######
            #find the source in the LAST reaction in the pathway
            #NOTE: this assumes that the source is contained in a single final reaction and nowhere else
            last_rid = None
            step_num = 1
            found_rid = []
            toFind_rid = list(reactions_list[pathNum].keys())
            for rid in reactions_list[pathNum]:
                if all([True if i in source_species else False for i in reactions_list[pathNum][rid]['right']]):
                    reactions_list[pathNum][rid]['step'] = step_num
                    #step_num -= 1
                    step_num += 1
                    last_rid = rid
                    try:
                        source_stochio[pathNum] = stochio[rid][source_cid[pathNum]]
                    except KeyError:
                        source_stochio[pathNum] = 1.0
                    found_rid.append(rid)
                    toFind_rid.remove(rid)
                    break
            for rid in toFind_rid[:]:
                if all([True if i in reactions_list[pathNum][last_rid]['left'] else False for i in reactions_list[pathNum][rid]['right']]):
                    reactions_list[pathNum][rid]['step'] = step_num
                    #step_num -= 1
                    step_num += 1
                    last_rid = rid
                    found_rid.append(rid)
                    toFind_rid.remove(rid)
            if not toFind_rid==[]:
                self.logger.error('There are reactions unaccounted for: '+str(toFind_rid))
                skip_pathway = True
                break
            ############# find all the alternative reactions associated with a reaction rule ###
            if not skip_pathway:
                rp_paths[pathNum] = {}
                for rid in reactions_list[pathNum]:
                    rp_paths[pathNum][reactions_list[pathNum][rid]['step']] = {}
                    sub_step = 1
                    for reac_id in self.rr_reactions[reactions_list[pathNum][rid]['rule_id']]:
                        tmpReac = copy.deepcopy(reactions_list[pathNum][rid])
                        tmpReac['mnxr'] = reac_id
                        tmpReac['sub_step'] = sub_step
                        rp_paths[pathNum][reactions_list[pathNum][rid]['step']][sub_step] = tmpReac
                        sub_step += 1
            else:
                self.logger.warning('Skipping pathway '+str(pathNum))
            pathNum += 1
        ######################################
        ########### create the SBML's ########
        ######################################
        try:
            mnxc = self.name_compXref[compartment_id]
        except KeyError:
            self.logger.error('Could not Xref compartment_id ('+str(compartment_id)+')')
            return False
        sbml_paths = {}
        for pathNum in rp_paths:
            #first level is the list of lists of sub_steps
            #second is itertools all possible combinations using product
            altPathNum = 1
            for comb_path in list(itertools_product(*[[(i,y) for y in rp_paths[pathNum][i]] for i in rp_paths[pathNum]])):
                steps = []
                for i, y in comb_path:
                    steps.append(rp_paths[pathNum][i][y])
                path_id = steps[0]['path_id']
                rpsbml = rpSBML.rpSBML('rp_'+str(path_id)+'_'+str(altPathNum))
                #1) create a generic Model, ie the structure and unit definitions that we will use the most
                ##### TODO: give the user more control over a generic model creation:
                #   -> special attention to the compartment
                rpsbml.genericModel('RetroPath_Pathway_'+str(path_id)+'_'+str(altPathNum),
                        'RP_model_'+str(path_id)+'_'+str(altPathNum),
                        self.compXref[mnxc],
                        compartment_id,
                        upper_flux_bound,
                        lower_flux_bound)
                #2) create the pathway (groups)
                rpsbml.createPathway(pathway_id)
                rpsbml.createPathway(species_group_id)
                #3) find all the unique species and add them to the model
                meta_to_cid = {}
                for meta in species_list[pathNum]:
                    #### beofre adding it to the model check to see if you can recover some MNXM from inchikey
                    #NOTE: only for the sink species do we try to convert to MNXM
                    if meta in list(sink_species[pathNum].keys()):
                        try:
                            #take the smallest MNX, usually the best TODO: review this
                            cid = sorted(self.inchikey_mnxm[sink_species[pathNum][meta]], key=lambda x: int(x[4:]))[0]
                            meta_to_cid[meta] = cid
                        except KeyError:
                            logging.error('Cannot find sink compound: '+str(meta))
                            return False
                    else:
                        cid = meta
                    # retreive the name of the molecule
                    #here we want to gather the info from rpReader's rp_strc and mnxm_strc
                    try:
                        chemName = self.mnxm_strc[meta]['name']
                    except KeyError:
                        chemName = None
                    #compile as much info as you can
                    #xref
                    try:
                        spe_xref = self.chemXref[meta]
                    except KeyError:
                        spe_xref = {}
                    #inchi
                    try:
                        spe_inchi = rp_strc[meta]['inchi']
                    except KeyError:
                        spe_inchi = None
                    #inchikey
                    try:
                        spe_inchikey = rp_strc[meta]['inchikey']
                    except KeyError:
                        spe_inchikey = None
                    #smiles
                    try:
                        spe_smiles = rp_strc[meta]['smiles']
                    except KeyError:
                        spe_smiles = None
                    #pass the information to create the species
                    rpsbml.createSpecies(meta,
                            compartment_id,
                            chemName,
                            spe_xref,
                            spe_inchi,
                            spe_inchikey,
                            spe_smiles,
                            species_group_id)
                #4) add the reactions and their annotations
                for step in steps:
                    #add the substep to the model
                    step['sub_step'] = altPathNum
                    #### try to replace the sink compounds inchikeys with mnxm
                    for direc in ['right', 'left']:
                        step_mnxm = {}
                        for meta in step[direc]:
                            try:
                                step_mnxm[meta_to_cid[meta]] = step[direc][meta]
                            except KeyError:
                                step_mnxm[meta] = step[direc][meta]
                        step[direc] = step_mnxm
                    rpsbml.createReaction('RP'+str(step['step']),
                            upper_flux_bound,
                            lower_flux_bound,
                            step,
                            compartment_id,
                            reac_smiles[pathNum][step['rule_id']],
                            {'ec': reac_ecs[pathNum][step['rule_id']]},
                            pathway_id)
                #5) adding the consumption of the target
                targetStep = {'rule_id': None,
                        'left': {source_cid[pathNum]: source_stochio[pathNum]},
                        'right': {},
                        'step': None,
                        'sub_step': None,
                        'path_id': None,
                        'transformation_id': None,
                        'rule_score': None,
                        'rule_ori_reac': None}
                rpsbml.createReaction('RP1_sink',
                        upper_flux_bound,
                        lower_flux_bound,
                        targetStep,
                        compartment_id)
                #6) Optional?? Add the flux objectives. Could be in another place, TBD
                rpsbml.createFluxObj('rpFBA_obj', 'RP1_sink', 1, True)
                sbml_paths['rp_'+str(step['path_id'])+'_'+str(altPathNum)] = rpsbml
                altPathNum += 1


    #############################################################################################
    ############################### TSV data tsv ################################################
    #############################################################################################


    ## Function to parse the TSV of measured heterologous pathways to SBML
    #
    # Given the TSV of measured pathways, parse them to a dictionnary, readable to next be parsed
    # to SBML
    #
    # @param self object pointer
    # @param inFile The input JSON file
    # @param mnxHeader Reorganise the results around the target MNX products
    # @return Dictionnary of SBML
    def _parseTSV(self, inFile, mnxHeader=False):
        data = {}
        try:
            for row in csv.DictReader(open(inFile), delimiter='\t'):
                ######## path_id ######
                try:
                    pathID = int(row['pathway_ID'])
                except ValueError:
                    self.logger.error('Cannot convert pathway ID: '+str(row['pathway_ID']))
                    continue
                if not pathID in data:
                    data[pathID] = {}
                    data[pathID]['isValid'] = True
                    data[pathID]['steps'] = {}
                ####### target #########
                if not 'target' in data[pathID]:
                    data[pathID]['target'] = {}
                    data[pathID]['target']['name'] = row['target_name']
                    data[pathID]['target']['inchi'] = row['target_structure']
                ####### step #########
                try:
                    stepID = int(row['step'])
                except ValueError:
                    self.logger.error('Cannot convert step ID: '+str(row['step']))
                    data[pathID]['isValid'] = False
                    continue
                if stepID==0:
                    continue
                elif stepID==1:
                    data[pathID]['organism'] = row['organism'].replace(' ', '')
                    data[pathID]['reference'] = row['reference'].replace(' ', '')
                data[pathID]['steps'][stepID] = {}
                ##### substrates #########
                data[pathID]['steps'][stepID]['substrates'] = []
                lenDBref = len(row['substrate_dbref'].split(';'))
                for i in row['substrate_dbref'].split(';'):
                    if i=='':
                        lenDBref -= 1
                lenStrc = len(row['substrate_structure'].split('_'))
                for i in row['substrate_structure'].split('_'):
                    if i=='':
                        lenStrc -= 1
                lenSub = len(row['substrate_name'].split(';'))
                for i in row['substrate_name'].split(';'):
                    if i=='':
                        lenSub -= 1
                if lenSub==lenStrc==lenSub:
                    for name, inchi, dbrefs in zip(row['substrate_name'].split(';'),
                            row['substrate_structure'].split('_'),
                            row['substrate_dbref'].split(';')):
                        tmp = {}
                        tmp['inchi'] = inchi.replace(' ', '')
                        tmp['name'] = name
                        tmp['dbref'] = {}
                        for dbref in dbrefs.split('|'):
                            if len(dbref.split(':'))==2:
                                db_name = dbref.split(':')[0].replace(' ', '').lower()
                                db_cid = dbref.split(':')[1].replace(' ', '')
                                if not db_name in tmp['dbref']:
                                    tmp['dbref'][db_name] = []
                                tmp['dbref'][db_name].append(db_cid)
                            else:
                                self.logger.warning('Ignoring the folowing product dbref ('+str(name)+'): '+str(dbref))
                                data[pathID]['isValid'] = False
                        data[pathID]['steps'][stepID]['substrates'].append(tmp)
                else:
                    self.logger.warning('Not equal length between substrate names, their structure or dbref ('+str(name)+'): '+str(row['substrate_name'])+' <--> '+str(row['substrate_structure'])+' <--> '+str(row['substrate_dbref']))
                    data[pathID]['isValid'] = False
                    continue
                ##### products #########
                data[pathID]['steps'][stepID]['products'] = []
                lenDBref = len(row['product_dbref'].split(';'))
                for i in row['product_dbref'].split(';'):
                    if i=='':
                        lenDBref -= 1
                lenStrc = len(row['product_structure'].split('_'))
                for i in row['product_structure'].split('_'):
                    if i=='':
                        lenStrc -= 1
                lenSub = len(row['product_name'].split(';'))
                for i in row['product_name'].split(';'):
                    if i=='':
                        lenSub -= 1
                if lenSub==lenStrc==lenDBref:
                    for name, inchi, dbrefs in zip(row['product_name'].split(';'),
                            row['product_structure'].split('_'),
                            row['product_dbref'].split(';')):
                        tmp = {}
                        tmp['inchi'] = inchi.replace(' ', '')
                        tmp['name'] = name
                        tmp['dbref'] = {}
                        for dbref in dbrefs.split('|'):
                            if len(dbref.split(':'))==2:
                                db_name = dbref.split(':')[0].replace(' ', '').lower()
                                db_cid = dbref.split(':')[1].replace(' ', '')
                                if not db_name in tmp['dbref']:
                                    tmp['dbref'][db_name] = []
                                tmp['dbref'][db_name].append(db_cid)
                            else:
                                data[pathID]['isValid'] = False
                                self.logger.warning('Ignoring the folowing product dbref ('+str(name)+'): '+str(dbref))
                        data[pathID]['steps'][stepID]['products'].append(tmp)
                else:
                    self.logger.warning('Not equal length between substrate names, their structure or dbref ('+str(name)+'): '+str(row['product_name'])+' <--> '+str(row['product_structure'])+' <--> '+str(row['product_dbref']))
                    data[pathID]['isValid'] = False
                if not row['uniprot']=='':
                    data[pathID]['steps'][stepID]['uniprot'] = row['uniprot'].replace(' ', '').split(';')
                if not row['EC_number']=='':
                    data[pathID]['steps'][stepID]['ec_numbers'] = [i.replace(' ', '') for i in row['EC_number'].split(';')]
                data[pathID]['steps'][stepID]['enzyme_id'] = [i.replace(' ', '') for i in row['enzyme_identifier'].split(';')]
                data[pathID]['steps'][stepID]['enzyme_name'] = row['enzyme_name'].split(';')
        except FileNotFoundError:
            self.logger.error('Cannot open the file: '+str(inFile))
        #now loop through all of them and remove the invalid paths
        toRet = copy.deepcopy(data)
        for path_id in data.keys():
            if toRet[path_id]['isValid']==False:
                del toRet[path_id]
            else:
                del toRet[path_id]['isValid']
        #reorganise the results around the target products mnx
        if not mnxHeader:
            return toRet
        else:
            toRetTwo = {}
            for path_id in toRet:
                try:
                    final_pro_mnx = toRet[path_id]['steps'][max(toRet[path_id]['steps'])]['products'][0]['dbref']['mnx'][0]
                except KeyError:
                    self.logger.error('The species '+str(toRet[path_id]['steps'][max(toRet[path_id]['steps'])]['products'][0]['name'])+' does not contain a mnx database reference... skipping whole pathway number '+str(path_id))
                    #continue
                if not final_pro_mnx in toRetTwo:
                    toRetTwo[final_pro_mnx] = {}
                toRetTwo[final_pro_mnx][path_id] = toRet[path_id]
            return toRetTwo


    ## Parse the validation TSV to SBML
    #
    # Parse the TSV file to SBML format and adds them to the self.sbml_paths
    #
    # @param self Object pointer
    # @param inFile Input file
    # @param compartment_id compartment of the
    def TSVtoSBML(self,
                  inFile,
                  tmpOutputFolder=None,
                  upper_flux_bound=99999,
                  lower_flux_bound=0,
                  compartment_id='MNXC3',
                  pathway_id='rp_pathway',
                  species_group_id='central_species'):
        data = self._parseTSV(inFile)
        sbml_paths = {}
        header_name = inFile.split('/')[-1].replace('.tsv', '').replace('.csv', '')
        #TODO: need to exit at this loop
        for path_id in data:
            try:
                mnxc = self.name_compXref[compartment_id]
            except KeyError:
                self.logger.error('Could not Xref compartment_id ('+str(compartment_id)+')')
                return False
            rpsbml = rpSBML.rpSBML(header_name+'_'+str(path_id))
            #1) create a generic Model, ie the structure and unit definitions that we will use the most
            ##### TODO: give the user more control over a generic model creation:
            #   -> special attention to the compartment
            rpsbml.genericModel(header_name+'_Path'+str(path_id),
                                header_name+'_Path'+str(path_id),
                                self.compXref[mnxc],
                                compartment_id,
                                upper_flux_bound,
                                lower_flux_bound)
            #2) create the pathway (groups)
            rpsbml.createPathway(pathway_id)
            rpsbml.createPathway(species_group_id)
            #3) find all the unique species and add them to the model
            allChem = []
            for stepNum in data[path_id]['steps']:
                #because of the nature of the input we need to remove duplicates
                for i in data[path_id]['steps'][stepNum]['substrates']+data[path_id]['steps'][stepNum]['products']:
                    if not i in allChem:
                        allChem.append(i)
            #add them to the SBML
            for chem in allChem:
                #PROBLEM: as it stands one expects the meta to be MNX
                if 'mnx' in chem['dbref']:
                    #must list the different models
                    meta = sorted(chem['dbref']['mnx'], key=lambda x : int(x.replace('MNXM', '')))[0]
                else:
                    #TODO: add the species with other types of xref in annotation
                    self.logger.warning('Some species are not referenced by a MNX id and will be ignored')
                    #try CHEBI
                    try:
                        meta = sorted(chem['dbref']['chebi'], key=lambda x : int(x))[0]
                        meta = 'CHEBI_'+str(meta)
                    except KeyError:
                        #TODO: need to find a better way
                        self.logger.warning('Cannot determine MNX or CHEBI entry, using random')
                        tmpDB_name = list(chem['dbref'].keys())[0]
                        meta = chem['dbref'][list(chem['dbref'].keys())[0]][0]
                        meta = str(tmpDB_name)+'_'+str(meta)
                    #break
                #try to conver the inchi into the other structures
                smiles = None
                inchikey = None
                try:
                    resConv = self._convert_depiction(idepic=chem['inchi'], itype='inchi', otype={'smiles','inchikey'})
                    smiles = resConv['smiles']
                    inchikey = resConv['inchikey']
                except NotImplementedError as e:
                    self.logger.warning('Could not convert the following InChI: '+str(chem['inchi']))
                #create a new species
                #here we want to gather the info from rpReader's rp_strc and mnxm_strc
                try:
                    chemName = self.mnxm_strc[meta]['name']
                except KeyError:
                    chemName = meta
                #compile as much info as you can
                #xref
                try:
                    #TODO: add the xref from the document
                    spe_xref = self.chemXref[meta]
                except KeyError:
                    #spe_xref = {}
                    spe_xref = chem['dbref']
                #inchi
                try:
                    spe_inchi = self.mnxm_strc[meta]['inchi']
                except KeyError:
                    spe_inchi = chem['inchi']
                #inchikey
                try:
                    spe_inchikey = self.mnxm_strc[meta]['inchikey']
                except KeyError:
                    spe_inchikey =  resConv['inchikey']
                #smiles
                try:
                    spe_smiles = self.mnxm_strc[meta]['smiles']
                except KeyError:
                    spe_smiles = resConv['smiles']
                #pass the information to create the species
                rpsbml.createSpecies(meta,
                        compartment_id,
                        chemName,
                        spe_xref,
                        spe_inchi,
                        spe_inchikey,
                        spe_smiles,
                        species_group_id)
            #4) add the complete reactions and their annotations
            #create a new group for the measured pathway
            #need to convert the validation to step for reactions
            for stepNum in data[path_id]['steps']:
                toSend = {'left': {}, 'right': {}, 'rule_id': None, 'rule_ori_reac': None, 'rule_score': None, 'path_id': path_id, 'step': stepNum, 'sub_step': None}
                for chem in data[path_id]['steps'][stepNum]['substrates']:
                    if 'mnx' in chem['dbref']:
                        meta = sorted(chem['dbref']['mnx'], key=lambda x : int(x.replace('MNXM', '')))[0]
                        #try CHEBI
                    else:
                        self.logger.warning('Not all the species to have a MNX ID')
                        #break
                        try:
                            meta = sorted(chem['dbref']['chebi'], key=lambda x : int(x))[0]
                            meta = 'CHEBI_'+str(meta)
                        except KeyError:
                            #TODO: need to find a better way
                            self.logger.warning('Cannot determine MNX or CHEBI entry, using random')
                            tmpDB_name = list(chem['dbref'].keys())[0]
                            meta = chem['dbref'][list(chem['dbref'].keys())[0]][0]
                            meta = str(tmpDB_name)+'_'+str(meta)
                    toSend['left'][meta] = 1
                for chem in data[path_id]['steps'][stepNum]['products']:
                    if 'mnx' in chem['dbref']:
                        meta = sorted(chem['dbref']['mnx'], key=lambda x : int(x.replace('MNXM', '')))[0]
                        #try CHEBI
                    else:
                        self.logger.warning('Need all the species to have a MNX ID')
                        try:
                            meta = sorted(chem['dbref']['chebi'], key=lambda x : int(x))[0]
                            meta = 'CHEBI_'+str(meta)
                        except KeyError:
                            #TODO: need to find a better way
                            self.logger.warning('Cannot determine MNX or CHEBI entry, using random')
                            tmpDB_name = list(chem['dbref'].keys())[0]
                            meta = chem['dbref'][list(chem['dbref'].keys())[0]][0]
                            meta = str(tmpDB_name)+'_'+str(meta)
                    toSend['right'][meta] = 1
                        #break
                #if all are full add it
                reac_xref = {}
                if 'ec_numbers' in data[path_id]['steps'][stepNum]:
                    reac_xref['ec'] = data[path_id]['steps'][stepNum]['ec_numbers']
                if 'uniprot' in data[path_id]['steps'][stepNum]:
                    reac_xref['uniprot'] = data[path_id]['steps'][stepNum]['uniprot']
                rpsbml.createReaction(header_name+'_Step'+str(stepNum),
                                      upper_flux_bound,
                                      lower_flux_bound,
                                      toSend,
                                      compartment_id,
                                      None,
                                      reac_xref,
                                      pathway_id)
                if stepNum==1:
                    #adding the consumption of the target
                    targetStep = {'rule_id': None,
                            'left': {},
                            'right': {},
                            'step': None,
                            'sub_step': None,
                            'path_id': None,
                            'transformation_id': None,
                            'rule_score': None,
                            'rule_ori_reac': None}
                    for chem in data[path_id]['steps'][stepNum]['products']:
                        try:
                            #smallest MNX
                            meta = sorted(chem['dbref']['mnx'], key=lambda x : int(x.replace('MNXM', '')))[0]
                        except KeyError:
                            #try CHEBI
                            try:
                                meta = sorted(chem['dbref']['chebi'], key=lambda x : int(x))[0]
                                meta = 'CHEBI_'+str(meta)
                            except KeyError:
                                self.logger.warning('Cannot determine MNX or CHEBI entry, using random')
                                tmpDB_name = list(chem['dbref'].keys())[0]
                                meta = chem['dbref'][list(chem['dbref'].keys())[0]][0]
                                meta = str(tmpDB_name)+'_'+str(meta)
                        targetStep['left'][meta] = 1
                    rpsbml.createReaction(header_name+'_Step1_sink',
                                          upper_flux_bound,
                                          lower_flux_bound,
                                          targetStep,
                                          compartment_id)
                    rpsbml.createFluxObj('rpFBA_obj', header_name+'_Step1_sink', 1, True)
            if tmpOutputFolder:
                rpsbml.writeSBML(tmpOutputFolder)
            else:
                sbml_paths[header_name+'_Path'+str(path_id)] = rpsbml
        if tmpOutputFolder:
            return {}
        else:
            return sbml_paths



    '''
    ######################################################
    ################## string to sbml ####################
    ######################################################
    ##
    # react_string: '1 MNX:MNXM181 + 1 MNX:MNXM4 => 2 MNX:MNXM1 + 1 MNX:MNXM11441'
    # ec: []
    def reacStr_to_sbml(self,
                        reac_sctring,
                        ec=[])
        #[{'reactants': [{'inchi': 'ajsjsjsjs', 'db_name': 'mnx', 'name': 'species1', 'id': 'MNXM181'}], 'products': [{'inchi': 'jdjdjdjdj', 'db_name': 'mnx', 'name': 'product1', 'id': 'MNXM1'}], 'ec': [{'id': '1.1.1.1'}]}]
        reac_species = [{'stoichio': i.split(' ')[0],
                         'inchi': '',
                         'name': i.split(' ')[0].split(':')[1],
                         'db_name': i.split(' ')[0].split(':')[0].lower(),
                         'id': i.split(' ')[0].split(':')[1]}  for i in reac_sctring.split('=>')[0].split('+')]
        reac_products = [{'stoichio': i.split(' ')[1],
                          'inchi': '',
                          'name': i.split(' ')[1].split(':')[1],
                          'db_name': i.split(' ')[1].split(':')[0].lower(),
                          'id': i.split(' ')[1].split(':')[1]}  for i in reac_sctring.split('=>')[0].split('+')]
        reac = [{'reactants': reac_species,
                 'products': reac_products,
                 'ec': [{'id': i} for i in ec]}]
	########### create CSV from input ##########
	with tempfile.TemporaryDirectory() as tmpOutputFolder:
		with open(tmpOutputFolder+'/tmp_input.tsv', 'w') as infi:
			csvfi = csv.writer(infi, delimiter='\t', quotechar='"', quoting=csv.QUOTE_MINIMAL)
			header = ['pathway_ID',
                                  'target_name',
                                  'target_structure',
                                  'step',
                                  'substrate_name',
                                  'substrate_dbref',
                                  'substrate_structure',
                                  'product_name',
                                  'product_dbref',
                                  'product_structure',
                                  'EC_number',
                                  'enzyme_identifier',
                                  'enzyme_name',
                                  'organism',
                                  'yield',
                                  'comments',
                                  'pictures',
                                  'pdf',
                                  'reference',
                                  'estimated time',
                                  'growth media']
			csvfi.writerow(header)
			first_line = ['1',
                                      'void',
                                      'test',
                                      '0',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '',
                                      '']
			csvfi.writerow(first_line)
			reac_count = len(reac)
			for reaction in reac:
				reac = ';'.join([i['id'] for i in reaction['reactants']])
				to_write = ['1',
					input_dict['target_name'],
					input_dict['target_inchi'],
					str(reac_count),
					';'.join([i['name'] for i in reaction['reactants']]),
					';'.join([i['db_name']+':'+i['id'] for i in reaction['reactants']]),
					';'.join([i['inchi'] for i in reaction['reactants']]),
					';'.join([i['name'] for i in reaction['products']]),
					';'.join([i['db_name']+':'+i['id'] for i in reaction['products']]),
					';'.join([i['inchi'] for i in reaction['products']]),
					';'.join([i['id'] for i in reaction['ec']]),
					'',
					'',
					'',
					'',
					'',
					'',
					'',
					'',
					'',
					'']
				csvfi.writerow(to_write)
				reac_count -= 1
		############## create SBML from CSV #####
		### rpReader #####
		rpreader = rpReader.rpReader()
		rpcache = rpToolCache.rpToolCache()
		rpreader.deprecatedMNXM_mnxm = rpcache.deprecatedMNXM_mnxm
		rpreader.deprecatedMNXR_mnxr = rpcache.deprecatedMNXR_mnxr
		rpreader.mnxm_strc = rpcache.mnxm_strc
		rpreader.inchikey_mnxm = rpcache.inchikey_mnxm
		rpreader.rr_reactions = rpcache.rr_reactions
		rpreader.chemXref = rpcache.chemXref
		rpreader.compXref = rpcache.compXref
		rpreader.name_compXref = rpcache.name_compXref
		##################
		#measured_pathway = parseValidation(tmpOutputFolder+'/tmp_input.csv')
		measured_sbml_paths = rpreader.validationToSBML(tmpOutputFolder+'/tmp_input.tsv',
                                                                tmpOutputFolder+'/')
		#should be only one
		measured_sbml = glob.glob(tmpOutputFolder+'/*.sbml')[0]
    '''


def build_parser():
    parser = argparse.ArgumentParser('Python wrapper to parse RP2 to generate rpSBML collection')
    parser.add_argument('-rp2paths_compounds', type=str)
    parser.add_argument('-rp2_pathways', type=str)
    parser.add_argument('-rp2paths_pathways', type=str)
    parser.add_argument('-upper_flux_bound', type=int, default=999999)
    parser.add_argument('-lower_flux_bound', type=int, default=0)
    parser.add_argument('-maxRuleIds', type=int, default=2)
    parser.add_argument('-pathway_id', type=str, default='rp_pathway')
    parser.add_argument('-compartment_id', type=str, default='MNXC3')
    parser.add_argument('-species_group_id', type=str, default='central_species')
    parser.add_argument('-output', type=str)

    return parser

def entrypoint(params=sys.argv[1:]):
    parser = build_parser()

    args = parser.parse_args(params)

    if args.maxRuleIds<0:
        logging.error('Max rule ID cannot be less than 0: '+str(params.maxRuleIds))
        exit(1)
        outputTar_bytes = io.BytesIO()
        #### MEM #####
        """
        if not rp2Reader_mem(rpreader,
                    rp2paths_compounds,
                    rp2_pathways,
                    rp2paths_pathways,
                    int(upper_flux_bound),
                    int(lower_flux_bound),
                    int(maxRuleIds),
                    pathway_id,
                    compartment_id,
                    species_group_id,
                    outputTar):
            abort(204)
        """
    rpreader = rpReader()
    rpsbml_paths = rpreader.rp2ToSBML(
                             args.rp2paths_compounds,
                             args.rp2_pathways,
                             args.rp2paths_pathways,
                             None,
                             int(args.upper_flux_bound),
                             int(args.lower_flux_bound),
                             int(args.maxRuleIds),
                             args.pathway_id,
                             args.compartment_id,
                             args.species_group_id
                             )

    print(rpsbml_paths)

##
#
#
if __name__ == "__main__":

    entrypoint()

    # if not isOK:
    #     logging.error('Function returned an error')
    # ########IMPORTANT######
    # outputTar_bytes.seek(0)
    # #######################
    # with open(outputTar, 'wb') as f:
    #     shutil.copyfileobj(outputTar_bytes, f, length=131072)