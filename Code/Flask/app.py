import os
import re
import logging
#import requests
#import yaml
import datetime
import torch
from torch.utils.data import (DataLoader, RandomSampler, SequentialSampler,
                              TensorDataset)
from torch.utils.data.distributed import DistributedSampler
from tqdm import tqdm, trange

from torch.nn import CrossEntropyLoss, MSELoss
from scipy.stats import pearsonr, spearmanr
from sklearn.metrics import matthews_corrcoef, f1_score
from sklearn import metrics

from pytorch_pretrained_bert.file_utils import PYTORCH_PRETRAINED_BERT_CACHE, WEIGHTS_NAME, CONFIG_NAME
from pytorch_pretrained_bert.modeling import BertForSequenceClassification, BertConfig
from pytorch_pretrained_bert.tokenization import BertTokenizer
from pytorch_pretrained_bert.optimization import BertAdam, WarmupLinearSchedule

from flask import Flask, render_template, url_for, g, request, send_from_directory, abort, request_started, jsonify, send_file
from flask_cors import CORS
from flask_restful import Resource, reqparse
from flask_restful_swagger_2 import Api, swagger, Schema
from flask_json import FlaskJSON, json_response
from neo4j import GraphDatabase, basic_auth
from neo4j.exceptions import Neo4jError, ServiceUnavailable
from preprocess import extract_features
import neo4j.time

import codecs

DATABASE_USERNAME = ('neo4j')
DATABASE_PASSWORD = ('grand-buzzer-cake-pony-almanac-414')
DATABASE_URL = ('bolt://localhost:7687')
# template_dir = 'D:/university/uit/thesis/code/tmp/Thesis/templates/'
driver = GraphDatabase.driver(DATABASE_URL, auth=basic_auth(DATABASE_USERNAME, str(DATABASE_PASSWORD)))
app = Flask(__name__)
CORS(app)
FlaskJSON(app)
api = Api(app, title='DemoNeo4j', api_version='1.1.2')
app.config['SECRET_KEY'] = ('super secret guy')
logger = logging.getLogger(__name__)
class InputExample(object):
    """A single training/test example for simple sequence classification."""

    def __init__(self, text_a, text_b=None, text_c=None, label=None):
        """Constructs a InputExample.

        Args:
            guid: Unique id for the example.
            text_a: string. The untokenized text of the first sequence. For single
            sequence tasks, only this sequence must be specified.
            text_b: (Optional) string. The untokenized text of the second sequence.
            Only must be specified for sequence pair tasks.
            text_c: (Optional) string. The untokenized text of the third sequence.
            Only must be specified for sequence triple tasks.
            label: (Optional) string. The label of the example. This should be
            specified for train and dev examples, but not for test examples.
        """
        self.text_a = text_a
        self.text_b = text_b
        self.text_c = text_c
        self.label = label

def get_db():
    if not hasattr(g, 'neo4j_db'):
        g.neo4j_db = driver.session()
    return g.neo4j_db

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'neo4j_db'):
        g.neo4j_db.close()

@app.route('/')
def final():      
    return render_template('base.html')

# RESULT DISPLAY
# Get descriptions
def get_subjects(tx, s_name):
    def s_query(tx, s_name):
        result = tx.run(
                        'match (s:Subject) where s.name = $s_name return s.description as s_description'
                        , s_name=s_name)
        result = [record['s_description'] for record in result]
        return result
    db = get_db()
    result = db.read_transaction(s_query, s_name)
    result_s = [res for res in result]
    db.close()
    return result_s[0]

def get_relation(tx, r_name, s_name):
    def r_query(tx, r_name, s_name):
        result = tx.run(
                        'match (s:Subject)-[r:la]-(friends) where s.name = $s_name return r.description as r_description'
                        , s_name=s_name, r_name=r_name)
        result = [record['r_description'] for record in result]
        return result
    db = get_db()
    result = db.read_transaction(r_query, r_name, s_name)
    result_r = [res for res in result]
    db.close()
    return result_r[0]

def get_objects(tx, o_name):
    def o_query(tx, o_name):
        result = tx.run(
                        'match (o:Object) where o.name = $o_name return o.description as o_description'
                        , o_name=o_name)
        result = [record['o_description'] for record in result]
        return result
    db = get_db()
    result = db.read_transaction(o_query, o_name)
    result_o = [res for res in result]
    db.close()
    return result_o[0]

@app.route('/predict', methods=['POST'])
def predict():
    '''
    Get value from front-end
    Search in Neo4j to get their description as an input for model
    '''
    #get value from front-end
    
    value = {}
    # str_features = [str(x) for x in request.form.values()]
    # value['Subject'] = str_features[0]
    # value['Relation'] = str_features[1]
    # value['Object'] = str_features[2]
    value['Subject'] = request.form.get('subject')
    value['Relation'] = request.form.get('relation')
    value['Object'] = request.form.get('object')

    # Querying in Neo4j
    
    subj = get_subjects(driver, value['Subject'])
    re = get_relation(driver, value['Relation'], value['Subject'])
    obj = get_objects(driver, value['Object'])
    logging.warning(subj)
    #loadBERT
    tokenizer = BertTokenizer.from_pretrained('bert-base-cased', do_lower_case=False)
    model = torch.load('D:/university/uit/thesis/an_cuong/final/model/model.pth')
    #variable_prepare
    examples = []
    examples.append(InputExample(text_a = subj, text_b = re, text_c = obj, label="1"))
    features = extract_features(examples, label_lst="1", max_seq_length=200, tokenizer=tokenizer)
    #load_data_to_model
    input_ids = torch.tensor([f.input_ids for f in features], dtype=torch.long)
    input_mask = torch.tensor([f.input_mask for f in features], dtype=torch.long)
    segment_ids = torch.tensor([f.segment_ids for f in features], dtype=torch.long)
    label_ids = torch.tensor([f.label_id for f in features], dtype=torch.long)
    #Processing
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    input_ids = input_ids.to(device)
    input_mask = input_mask.to(device)
    segment_ids = segment_ids.to(device)
    output = model(input_ids, segment_ids, input_mask, labels=None)
    output = torch.nn.Softmax()(output[0]).cpu().detach().numpy()
    logging.warning(output)

    if output[1] >= 0.5:
        predicted_string =  ' TRUE - This triple is existent in the description!'
    else:
        predicted_string = ' FALSE - This triple is not existent in the description!'
    
    # What variable will be returned to second page
    prediction = {'prediction_key': predicted_string}
    subjects = {'subject_key': value['Subject']}
    relation = {'relation_key':value['Relation']}
    objects = {'object_key':value['Object']}

    def gen_org():
        if request.method == 'POST':
            value = {}
            value['Subject'] = request.form.get('subject')
            value['Relation'] = request.form.get('relation')
            value['Object'] = request.form.get('object')
            subj = get_subjects(driver, value['Subject'])
            re = get_relation(driver, value['Relation'], value['Subject'])
            obj = get_objects(driver, value['Object'])
            logging.warning(subj)

            subj = subj.encode().decode("utf-8") 
            re = re.encode().decode("utf-8")
            obj = obj.encode().decode("utf-8")

            desc_text = subj + ' ' + obj # temporarily remove relation description
            desc_filename = 'original.txt'
            desc_file = codecs.open('temp_files/' + desc_filename, 'w', "utf-8") # path specified by terminal
            desc_file.write(desc_text)
            desc_file.close()

    # print(objects['object_key'])
    # return (render_template('base.html', prediction=prediction, subjects=subjects, relation=relation, objects=objects))
    gen_org()
    return render_template('base.html', prediction_text='{}'.format(predicted_string))

# downloading
@app.route('/download_org')
def download_org(): 
    file = 'temp_files/original.txt'
    return send_file(file, as_attachment=True)

@app.route('/download_rand1')
def download_rd1(): 
    file = 'temp_files/random1.txt'
    return send_file(file, as_attachment=True)

@app.route('/download_rand2')
def download_rd2(): 
    file = 'temp_files/random2.txt'
    return send_file(file, as_attachment=True)

# @app.route('/predict', method=['POST'])

if __name__ == "__main__":
    app.run(debug=True) 
