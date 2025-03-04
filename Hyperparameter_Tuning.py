########################################################################################################################
# info: Hyperparameter Tuning
########################################################################################################################
# Random Grid Search of different hyperparameter sets for automated accumulated model training.

########################################################################################################################
# Import necessary libraries and modules
########################################################################################################################
from __future__ import division
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import os
import time
import random
# from sklearn.model_selection import ParameterGrid
import numpy as np
import itertools
import argparse
import json

import Training
import Tools

########################################################################################################################
# Create HP combinations and randomly choose a selection
########################################################################################################################
def create_param_combinations(param_grid, sample_size):
    # Create all possible combinations of parameters
    keys, values = zip(*param_grid.items())
    all_combinations = [dict(zip(keys, combination)) for combination in itertools.product(*values)]

    # Randomly sample the specified number of combinations
    sampled_combinations = random.sample(all_combinations, sample_size)

    return sampled_combinations

def create_repeated_param_combinations(param_grid, sample_size):
    # Create the single combination of parameters
    keys, values = zip(*param_grid.items())
    single_combination = dict(zip(keys, [v[0] for v in values]))

    # Return the same combination 'sample_size' times
    repeated_combinations = [single_combination for _ in range(sample_size)]

    return repeated_combinations

# Get input and output dimension for network, depending on higDim and lowDim data and ruleset (standard: 'all')
num_ring = Tools.get_num_ring('all')
n_rule = Tools.get_num_rule('all')

# # attention: hitkip cluster ############################################################################################
# # info: hps defined in .sbatch job scheduler file
# # Set up argument parser
# parser = argparse.ArgumentParser(description="Train RNN with specific parameters.")
# parser.add_argument("--adjParams", type=str, required=True, help="JSON-encoded parameters")
# # Parse arguments
# args = parser.parse_args()
# try:
#     adjParams = json.loads(args.adjParams)
# except json.JSONDecodeError as e:
#     raise ValueError(f"Failed to decode adjParams JSON: {e}")
# # attention: hitkip cluster ############################################################################################


# attention: all other setups ##########################################################################################
data = ['data_lowDim_correctOnly'] # 'data_highDim' , data_highDim_correctOnly , data_highDim_lowCognition , data_lowDim , data_lowDim_correctOnly , data_lowDim_lowCognition

if 'highDim' in data[0]:
    n_eachring = 32
    n_outputring = n_eachring
    n_input, n_output = 1 + num_ring * n_eachring + n_rule, n_outputring + 1
else:
    n_eachring = 10
    n_outputring = 2
    n_input, n_output = 1 + num_ring * n_eachring + n_rule, n_outputring + 1

# Info: After first HPs the most probable space inheriting the best solution decreased to the following
adjParams = {
    'batch_size': [40, 80, 120],
    'in_type': ['normal'],
    'rnn_type': ['LeakyRNN','LeakyGRU'],
    'n_input': [n_input], # number of input units
    'n_output': [n_output], # number of output units
    'use_separate_input': [False],
    'loss_type': ['lsq'],
    'optimizer': ['adam'], # 'sgd'
    'activation': ['relu', 'tanh', 'softplus'], # 'elu'
    'tau': [40, 80, 100], # Decides how fast previous information decays to calculate current state activity
    'dt': [20],
    # 'alpha': 0.2,
    'sigma_rec': [0, 0.05],
    'sigma_x': [0, 0.01],
    'w_rec_init': ['randortho', 'randgauss'],
    'l1_h': [0, 0.00000005],
    'l2_h': [0, 0.00000005],
    'l1_weight': [0, 0.00000001],
    'l2_weight': [0, 0.00000001],
    'l2_weight_init': [0],
    'p_weight_train': [None, 0.05, 0.1],
    'w_mask_value': [0.1], # default .1 - value that will be multiplied with L2 regularization (combined with p_weight_train), <1 will decrease it
    'learning_rate': [0.001, 0.0005],
    'learning_rate_mode': [None, 'triangular', 'triangular2', 'exp_range'], # Will overwrite learning_rate if it is not None - 'triangular', 'triangular2', 'exp_range'
    'base_lr': [0.0005],
    'max_lr': [0.001],
    'n_rnn': [64, 128, 256],
    'c_mask_responseValue': [5., 3., 1.],
    'monthsConsidered': [['month_3', 'month_4', 'month_5']], # list of lists
    'monthsString': ['3-5'],
    # 'rule_prob_map': {"DM": 1,"DM_Anti": 1,"EF": 1,"EF_Anti": 1,"RP": 1,"RP_Anti": 1,"RP_Ctx1": 1,"RP_Ctx2": 1,"WM": 1,"WM_Anti": 1,"WM_Ctx1": 1,"WM_Ctx2": 1}
    'rule_prob_map': [{"DM": 1,"DM_Anti": 1,"EF": 1,"EF_Anti": 1,"RP": 1,"RP_Anti": 1,"RP_Ctx1": 1,"RP_Ctx2": 1,"WM": 1,"WM_Anti": 1,"WM_Ctx1": 1,"WM_Ctx2": 1}], # fraction of tasks represented in training data
    'participant': ['beRNN_03'], # Participant to take
    'data': data,
    'machine': ['local'], # 'local' 'pandora' 'hitkip'
    'tasksString': ['AllTask'], # tasksTaken
    'sequenceMode': [True], # Decide if models are trained sequentially month-wise
    'trainingBatch': ['01'],
    'trainingYear_Month': ['2025_03']
}
# attention: all other setups ##########################################################################################


# Randomly sample combinations
sampled_combinations = create_param_combinations(adjParams, 50)

# # Create one combination and repeat it according to sample_size
# sampled_repeated_combinations = create_repeated_param_combinations(best_params, 5)


# Training #############################################################################################################
# Initialize list for all training times for each model
trainingTimeList = []
# Measure time for every model, respectively
trainingTimeTotal_hours = 0
# Example iteration through the grid
for modelNumber, params in enumerate(sampled_combinations): # info: either sampled_combinations OR sampled_repeated_combinations

    # Start
    start_time = time.perf_counter()
    print(f'START TRAINING MODEL: {modelNumber}')

    print(params)
    print(modelNumber)

    print('START TRAINING FOR NEW MODEL')

    load_dir = None

    # Define main path
    if params['machine'] == 'local':
        path = 'C:\\Users\\oliver.frank\\Desktop\\BackUp'
    elif params['machine'] == 'hitkip':
        path = '/zi/home/oliver.frank/Desktop'
    elif params['machine'] == 'pandora':
        path = '/pandora/home/oliver.frank/01_Projects/RNN/multitask_BeRNN-main'

    # Define data path
    preprocessedData_path = os.path.join(path, 'Data', params['participant'], params['data'])

    for month in params['monthsConsidered']:  # attention: You have to delete this if cascade training should be set OFF
        # Adjust variables manually as needed
        model_name = f'model_{month}'

        # Define model_dir for different servers
        if params['machine'] == 'local':
            model_dir = os.path.join(
                f"{path}\\beRNNmodels\\{params['trainingYear_Month']}\\{params['trainingBatch']}\\{params['participant']}_{params['tasksString']}_{params['monthsString']}_{params['data']}_iteration{modelNumber}_{params['rnn_type']}_{params['n_rnn']}_{params['activation']}",
                model_name)
        elif params['machine'] == 'hitkip' or params['machine'] == 'pandora':
            model_dir = os.path.join(
                f"{path}/beRNNmodels/{params['trainingYear_Month']}/{params['trainingBatch']}/{params['participant']}_{params['tasksString']}_{params['monthsString']}_{params['data']}_iteration{modelNumber}_{params['rnn_type']}_{params['n_rnn']}_{params['activation']}",
                model_name)

        print('MODELDIR: ', model_dir)

        if not os.path.exists(model_dir):
            os.makedirs(model_dir)

        # Split the data ---------------------------------------------------------------------------------------------------
        # List of the subdirectories
        subdirs = [os.path.join(preprocessedData_path, d) for d in os.listdir(preprocessedData_path) if os.path.isdir(os.path.join(preprocessedData_path, d))]

        # Initialize dictionaries to store training and evaluation data
        train_data = {}
        eval_data = {}

        # Function to split the files
        for subdir in subdirs:
            # Collect all file triplets in the current subdirectory
            file_triplets = []
            for file in os.listdir(subdir):
                if file.endswith('Input.npy'):
                    # III: Exclude files with specific substrings in their names
                    # if any(exclude in file for exclude in ['Randomization', 'Segmentation', 'Mirrored', 'Rotation']):
                    #     continue
                    if month not in file:  # Sort out months which should not be considered
                        continue
                    # Add all necessary files to triplets
                    base_name = file.split('Input')[0]
                    input_file = os.path.join(subdir, base_name + 'Input.npy')
                    yloc_file = os.path.join(subdir, base_name + 'yLoc.npy')
                    output_file = os.path.join(subdir, base_name + 'Output.npy')
                    file_triplets.append((input_file, yloc_file, output_file))

            # Split the file triplets
            train_files, eval_files = Training.split_files(file_triplets)

            # Store the results in the dictionaries
            train_data[subdir] = train_files
            eval_data[subdir] = eval_files

        try:
            # Start Training ---------------------------------------------------------------------------------------------------
            Training.train(model_dir=model_dir, train_data=train_data, eval_data=eval_data, hp=params, load_dir=load_dir)

        except:
            print("An exception occurred with model number: ", modelNumber)

        # info: If True previous model parameters will be taken to initialize consecutive model, creating sequential training
        if params['sequenceMode'] == True:
            load_dir = model_dir

    end_time = time.perf_counter()
    elapsed_time_seconds = end_time - start_time
    elapsed_time_minutes = elapsed_time_seconds / 60
    elapsed_time_hours = elapsed_time_minutes / 60

    print(f"TIME TAKEN TO TRAIN MODEL {modelNumber}: {elapsed_time_seconds:.2f} seconds")
    print(f"TIME TAKEN TO TRAIN MODEL {modelNumber}: {elapsed_time_minutes:.2f} minutes")
    print(f"TIME TAKEN TO TRAIN MODEL {modelNumber}: {elapsed_time_hours:.2f} hours")

    # Accumulate trainingTime
    trainingTimeList.append(elapsed_time_hours)
    trainingTimeTotal_hours += elapsed_time_hours


# Save training time total and list to folder as a text file
file_path = model_dir.split('beRNN_')[0] + 'times.txt'

with open(file_path, 'w') as f:
    f.write(f"training time total (hours): {trainingTimeTotal_hours}\n")
    f.write("training time each individual model (hours):\n")
    for time in trainingTimeList:
        f.write(f"{time}\n")

print(f"Training times saved to {file_path}")

