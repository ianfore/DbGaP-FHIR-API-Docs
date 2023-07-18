import os
import sys
import json
import requests
import pandas as pd 
import numpy as np
from pathlib import Path
from datetime import datetime
import time
import pprint

class dbgapfhir:

    def __init__(self, fhir_server, verify_ssl = True, api_key=None, passport=None, debug=False, show_stats=True):
        
        # Optional: Turn off SSL verification. Useful when dealing with a corporate proxy with self-signed certificates.
        # This should be set to True unless you actually see certificate errors.

        if not verify_ssl:
            requests.packages.urllib3.disable_warnings()
            
        self.fhir_server = fhir_server
        self.api_key = api_key
        self.passport = passport
        self.debug = debug
        self.show_stats = show_stats

        # We make a requests.Session to ensure consistent headers/cookie across all the requests we make
        self.s = requests.Session()
        self.s.headers.update({'Accept': 'application/fhir+json'})
        # handle security needed for dbGaP
        self.__add_passport()
        self.s.verify = verify_ssl        
        self.bytes_retrieved = 0
        
        # Test out the client by querying the server metadata#
        r = self.s.get(f"{self.fhir_server}/metadata")

        if "<!DOCTYPE html>" in r.text:
            sys.stderr.write('ERROR: Could not get the server capability statement. ')

    # Resolves all pages for the bundle. Returns an array with all Bundles, including the original Bundle.
    def resolve_pages(self, bundle, debug=False, sleep=None):

        max_tries = 10 # maximum number of tries to get next page
        retry_sleep = 10 # after multiple failures, wait this number of seconds for a retry
        try:
            next_page_link = next(filter(lambda link: link['relation'] == 'next', bundle['link']), None)
        except KeyError:
            print('Key error link/next_page')
            print(json.dumps(bundle, indent=3))
            raise
        n = 1
        if next_page_link:
            if sleep != None:
                time.sleep(sleep)
            fhir_query = next_page_link['url']
            if self.api_key != None:
                fhir_query += f"&api_key={self.api_key}"
            if debug:
                print('_'*80)
                print(fhir_query)
            tries = 1
            r = self.s.get(fhir_query)
            while r.status_code == 500 and tries < max_tries:
            	tries += 1
            	if tries > 6:
            		time.sleep(retry_sleep)
            		print (f"trying again - waiting {retry_sleep}s")
            	else:
            		print ("trying again")
            	r = self.s.get(fhir_query)
            if tries > 1:
            	print(f'took {tries} tries')
            next_page = r.json()
            self.bytes_retrieved += len(r.content)
            if 'link' not in next_page:
                print(json.dumps(next_page, indent=3))
            nl = [l for l in next_page['link'] if l['relation'] == 'next']
            if debug:
                if len(nl) < 1:
                    print('Full last response')
                    print(json.dumps(next_page, indent=3))
            return [bundle] + self.resolve_pages(next_page, debug, sleep)
        else:
            return [bundle]

    # NOTE: No cell output.

    # Run a query, and get the whole set of results back as a list of resources
    # Set limit to True if you want  to the first page if you like
    def run_query(self, query, limit=None, debug=False, sleep=None, show_stats=None):
    
        if show_stats == None:
            show_stats = self.show_stats
            
        t_start = time.perf_counter()

        self.bytes_retrieved = 0
        subset = False
        
        fhir_query = f"{self.fhir_server}/{query}"
        if self.api_key != None:
            fhir_query += f"&api_key={self.api_key}"
        if debug:
            print(fhir_query)
        r = self.s.get(fhir_query)
        first_bundle = r.json()
        self.bytes_retrieved += len(r.content)
        if debug:
            print(json.dumps(first_bundle, indent=3))
            print('got response')
        # if it's just a summary
        if 'meta' in first_bundle and 'tag' in first_bundle['meta'] and first_bundle['meta']['tag'][0]['code'] == 'SUBSETTED':
                subset = True
        elif limit == None:
            all_bundles = self.resolve_pages(first_bundle, debug, sleep)
        else:
            all_bundles = [first_bundle]

        t_end = time.perf_counter()
        
        resources = []
        if subset:
            resources = [first_bundle]
        else:
            resources = []
            for bundle in all_bundles:
                if 'entry' in bundle:
                    resources.extend([entry['resource']  for entry in bundle['entry']])
        
        elapsed = t_end - t_start
        if show_stats:
            print(f"Total  Resources: {len(resources)}")
            print(f"Total  Bytes: {self.bytes_retrieved}")
            print(f"Time elapsed {elapsed:0.4f} seconds")
        return resources
        
    # Run a query, and get the whole set of results back as a list of resources
    # Set limit to True if you want  to the first page if you like
    def postQuery(self, query, limit=None, debug=False, sleep=None, show_stats=True):
    
        t_start = time.perf_counter()

        self.bytes_retrieved = 0
        
        fhir_query = f"{self.fhir_server}/{query}"
        if self.api_key != None:
            fhir_query += f"&api_key={self.api_key}"
        if debug:
            print(fhir_query)
        r = self.s.post(fhir_query)
        first_bundle = r.json()
        self.bytes_retrieved += len(r.content)
        if debug:
            print(json.dumps(first_bundle, indent=3))
            print('got response')
        if limit == None:
            all_bundles = self.resolve_pages(first_bundle, debug, sleep)
        else:
            all_bundles = [first_bundle]

        t_end = time.perf_counter()
        
        resources = []
        for bundle in all_bundles:
            if 'entry' in bundle:
                resources.extend([entry['resource']  for entry in bundle['entry']])
        
        elapsed = t_end - t_start
        if show_stats:
            print(f"Total  Resources: {len(resources)}")
            print(f"Total  Bytes: {self.bytes_retrieved}")
            print(f"Time elapsed {elapsed:0.4f} seconds")
        return resources
        
    def __add_passport(self, passport=None):
        '''Adds Passport/TST to session header
        '''
        if passport == None:
            passport = self.passport
        
        if passport != None:
            full_key_path = os.path.expanduser(passport)
            file_content = ""
            if self.debug: print(f"passport path {full_key_path}")
            try:
                with open(full_key_path) as f:
                    file_content = f.read()
                if self.debug: print(f"content of passport file {file_content}")
                self.s.headers.update({'Authorization': f'Bearer {file_content}'})
            except:
                print("Could not find passport file")

def obs_to_df(observations):
    patient_observations_dict = {}
    
    for obs in observations:
        subject_id = obs['subject']['reference']
        obs_display_name = obs['code']['coding'][0]['display']
        if obs_display_name in ['SUBJECT_ID','SAMPLE_ID']:
            obs_code = obs['code']['coding'][0]['code']
            obs_display_name = f'{obs_display_name}_{obs_code}'
        if 'valueQuantity' in obs:
            value_text = obs['valueQuantity']['value']
            #value_unit = obs['valueQuantity']['unit']
        elif 'valueCodeableConcept' in obs:
             value_text = obs['valueCodeableConcept']['coding'][0]['display']
        else:
            value_text = 'unknown'

        if subject_id not in patient_observations_dict:
            patient_observations_dict[subject_id] = {obs_display_name: value_text}
        else:
            patient_observations_dict[subject_id][obs_display_name] = value_text

    df = pd.DataFrame.from_dict(patient_observations_dict, orient='index')
    return df
    
def prettyprint(some_json):
    print(json.dumps(some_json, indent=3))