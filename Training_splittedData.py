########################################################################################################################
# info: Training
########################################################################################################################
# Train Models with collected data. Particpant, data and directories have to be adjusted manually.
########################################################################################################################

########################################################################################################################
# Import necessary libraries and modules
########################################################################################################################
from __future__ import division

import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

import sys
import time
from collections import defaultdict

import os
import numpy as np
# import matplotlib.pyplot as plt
import tensorflow as tf
import random

from Network import Model, get_perf
# from analysis import variance
import Tools

########################################################################################################################
# Predefine functions
########################################################################################################################
def get_default_hp(ruleset):
    '''Get a default hp.

    Useful for debugging.

    Returns:
        hp : a dictionary containing training hpuration
    '''
    num_ring = Tools.get_num_ring(ruleset)
    n_rule = Tools.get_num_rule(ruleset)

    n_eachring = 32
    n_input, n_output = 1 + num_ring * n_eachring + n_rule, n_eachring + 1
    hp = {
        # batch size for training and evaluation
        'batch_size': 40, # info: Should be smaller than 40 or 40/80/120/160
        # batch_size for testing
        # 'batch_size_test': 640,
        # input type: normal, multi
        'in_type': 'normal',
        # Type of RNNs: NonRecurrent, LeakyRNN, LeakyGRU, EILeakyGRU, GRU, LSTM
        'rnn_type': 'LeakyRNN',
        # whether rule and stimulus inputs are represented separately
        'use_separate_input': False,
        # Type of loss functions
        'loss_type': 'lsq',
        # Optimizer
        'optimizer': 'adam',
        # Type of activation runctions, relu, softplus, tanh, elu, linear
        'activation': 'softplus',
        # Time constant (ms)
        'tau': 100,
        # discretization time step (ms)
        'dt': 20,
        # discretization time step/time constant info: dt/tau = alpha
        'alpha': 0.2,
        # recurrent noise - directly influencing the noise added to the network; can prevent over-fitting especially when learning time sequences
        'sigma_rec': 0.05, # info: Can be increased with higher amount of hidden units
        # input noise
        'sigma_x': 0.01,
        # leaky_rec weight initialization, diag, randortho, randgauss
        'w_rec_init': 'randortho',
        # a default weak regularization prevents instability (regularizing with absolute value of magnitude of coefficients, leading to sparse features)
        'l1_h': 0.00005, # info: The higher the amount of hidden_rnn, the stronger the regularization to prevent overfitting
        # l2 regularization on activity (regularizing with squared value of magnitude of coefficients, decreasing influence of features)
        'l2_h': 0.00005, # info: These values represent lambda which controls the strength of regularization
        # l2 regularization on weight
        'l1_weight': 0.00005,
        # l2 regularization on weight
        'l2_weight': 0.00005,
        # l2 regularization on deviation from initialization
        'l2_weight_init': 0,
        # proportion of weights to train, None or float between (0, 1) - e.g. .1 will train a random 10% weight selection, the rest stays fixed (Yang et al. range: .05-.075)
        'p_weight_train': None,
        # Stopping performance
        'target_perf': 1.0,
        # number of units each ring
        'n_eachring': n_eachring,
        # number of rings
        'num_ring': num_ring,
        # number of rules
        'n_rule': n_rule,
        # first input index for rule units
        'rule_start': 1 + num_ring * n_eachring,
        # number of input units
        'n_input': n_input,
        # number of output units
        'n_output': n_output,
        # number of recurrent units
        'n_rnn': 32, # info: check theshold to know what amount of parameters will be actually trained (e.g. 11: 128 parameters)
        # random number used for several random initializations
        'rng': np.random.RandomState(seed=0),
        # number of input units
        'ruleset': ruleset,
        # name to save
        'save_name': 'test',
        # learning rate
        'learning_rate': 0.001, # n_rnn:256 - 0.001; n_rnn:512 - 0.0001; n_rnn:1024 - 0.00007; n_rnn:2048 - 0.00004
        # c_mask response epoch value - info: How strong is the response epoch taken into account for caclulating error, the higher the more it influences the costs and therefore the parameter changes
        'c_mask_responseValue': 5.,
        # Structural mask
        's_mask': None # 'sc1000' None info: Make sure n_rnn has the same size as the chosen s_mask
        # intelligent synapses parameters, tuple (c, ksi) -> Yang et al. only apply these in sequential training
        # 'c_intsyn': 0,
        # 'ksi_intsyn': 0,
    }

    return hp

def split_files(files, split_ratio=0.8):
    random.seed(42) # info: add seed to always shuffle similiar - would be good for NetworkAnalysis
    random.shuffle(files)
    split_index = int(len(files) * split_ratio)
    return files[:split_index], files[split_index:]

def do_eval(sess, model, log, rule_train, eval_data):
    """Do evaluation.

    Args:
        sess: tensorflow session
        model: Model class instance
        log: dictionary that stores the log
        rule_train: string or list of strings, the rules being trained
    """
    hp = model.hp
    mode = 'eval'
    if not hasattr(rule_train, '__iter__'):
        rule_name_print = rule_train
    else:
        rule_name_print = ' & '.join(rule_train)

    print('Trial {:7d}'.format(log['trials'][-1]) +
          '  | Time {:0.2f} s'.format(log['times'][-1]) +
          '  | Now training ' + rule_name_print)

    for task in hp['rules']:
        if 'WM' in task:
            n_rep = 80 # info: four times the amount of normal training, because of splitted, smaller batch sizes (special small for WM tasks)
        else:
            n_rep = 40 # info: double the amount of normal training, because of splitted, smaller batch sizes
        # batch_size_test_rep = int(hp['batch_size_test']/n_rep)
        clsq_tmp = list()
        creg_tmp = list()
        perf_tmp = list()
        for i_rep in range(n_rep):
            x,y,y_loc = Tools.load_trials(task, mode, hp['batch_size'], eval_data, False)  # y_loc is participantResponse_perfEvalForm

            # info: ################################################################################################
            fixation_steps = Tools.getEpochSteps(y)
            if fixation_steps == None: # Especially important for the splitted WM trials, as they sometimes have 0 trials in one file (should be fixed by Marc)
                continue

            # Creat c_mask for current batch
            if hp['loss_type'] == 'lsq':
                c_mask = np.zeros((y.shape[0], y.shape[1], y.shape[2]), dtype='float32')
                for i in range(y.shape[1]):
                    # Fixation epoch
                    c_mask[:fixation_steps, i, :] = 1.
                    # Response epoch
                    c_mask[fixation_steps:, i, :] = hp['c_mask_responseValue'] # info: 1 or 5

                # self.c_mask[:, :, 0] *= self.n_eachring # Fixation is important
                # c_mask[:, :, 0] *= 2.  # Fixation is important
                c_mask = c_mask.reshape((y.shape[0]*y.shape[1], y.shape[2]))

            else:
                c_mask = np.zeros((y.shape[0], y.shape[1]), dtype='float32')
                for i in range(y.shape[1]):
                    # Fixation epoch
                    c_mask[:fixation_steps, i, :] = 1.
                    # Response epoch
                    c_mask[fixation_steps:, i, :] = hp['c_mask_responseValue'] # info: 1 or 5

                c_mask = c_mask.reshape((y.shape[0] * y.shape[1],))
                c_mask /= c_mask.mean()

            # info: ################################################################################################

            feed_dict = Tools.gen_feed_dict(model, x, y, c_mask, hp) # y: participnt response, that gives the lable for what the network is trained for
            # print('passed feed_dict Evaluation')
            # print(feed_dict)
            # print('x',type(x),x.shape)
            # print('y',type(y),y.shape)
            # print('y_loc',type(y_loc),y_loc.shape)
            c_lsq, c_reg, y_hat_test = sess.run([model.cost_lsq, model.cost_reg, model.y_hat],feed_dict=feed_dict)
            # print('passed sess.run')
            # Cost is first summed over time,
            # and averaged across batch and units
            # We did the averaging over time through c_mask
            perf_test = np.round(np.mean(get_perf(y_hat_test, y_loc)),3) # info: y_loc is participant response as groundTruth
            print('perf_test   ', perf_test)
            clsq_tmp.append(c_lsq)
            creg_tmp.append(c_reg)
            perf_tmp.append(perf_test)

        log['cost_' + task].append(np.mean(clsq_tmp, dtype=np.float64))
        log['creg_' + task].append(np.mean(creg_tmp, dtype=np.float64))
        log['perf_' + task].append(np.mean(perf_tmp, dtype=np.float64))
        print('{:15s}'.format(task) +
              '| cost {:0.6f}'.format(np.mean(clsq_tmp)) +
              '| c_reg {:0.6f}'.format(np.mean(creg_tmp)) +
              '  | perf {:0.2f}'.format(np.mean(perf_tmp)))
        sys.stdout.flush()

    # info: This needs to be fixed since now rules are strings
    if hasattr(rule_train, '__iter__'):
        rule_tmp = rule_train
    else:
        rule_tmp = [rule_train]
    perf_tests_mean = np.mean([log['perf_' + r][-1] for r in rule_tmp])
    log['perf_avg'].append(perf_tests_mean)

    perf_tests_min = np.min([log['perf_' + r][-1] for r in rule_tmp])
    log['perf_min'].append(perf_tests_min)

    # Saving the model
    model.save()
    Tools.save_log(log)

    return log

def train(model_dir,train_data ,eval_data, subdir, hp=None,max_steps=3e6,display_step=500,ruleset='all',rule_trains=None,rule_prob_map=None,seed=0,
          load_dir=None,trainables=None):
    """Train the network.

    Args:
        model_dir: str, training directory
        hp: dictionary of hyperparameters
        max_steps: int, maximum number of training steps
        display_step: int, display steps
        ruleset: the set of rules to train
        rule_trains: list of rules to train, if None then all rules possible
        rule_prob_map: None or dictionary of relative rule probability
        seed: int, random seed to be used

    Returns:
        model is stored at model_dir/model.ckpt
        training configuration is stored at model_dir/hp.json
    """

    Tools.mkdir_p(model_dir)

    # Network parameters
    default_hp = get_default_hp(ruleset)
    # default_hp = get_default_hp('all')
    if hp is not None:
        default_hp.update(hp)
    hp = default_hp
    hp['seed'] = seed
    hp['rng'] = np.random.RandomState(seed)

    # Rules to train and test. Rules in a set are trained together
    if rule_trains is None:
        # By default, training all rules available to this ruleset
        hp['rule_trains'] = Tools.rules_dict[ruleset]
    else:
        hp['rule_trains'] = rule_trains
    hp['rules'] = hp['rule_trains']

    # Assign probabilities for rule_trains.
    if rule_prob_map is None:
        rule_prob_map = dict()

    # Turn into rule_trains format
    hp['rule_probs'] = None
    if hasattr(hp['rule_trains'], '__iter__'):
        # Set default as 1.
        rule_prob = np.array([rule_prob_map.get(r, 1.) for r in hp['rule_trains']])
        hp['rule_probs'] = list(rule_prob / np.sum(rule_prob))
    Tools.save_hp(hp, model_dir)

    # # info: Create structural mask to multiply with hidden layer
    # if hp['s_mask'] == 'sc1000':
    #     import scipy.io
    #     sc1000 = scipy.io.loadmat('C:\\Users\\oliver.frank\\Desktop\\BackUp\\art_BeRNN\\sc1000')
    #     # sc100 = scipy.io.loadmat('C:\\Users\\oliver.frank\\Desktop\\BackUp\\art_BeRNN\\sc100')
    #     # sc1000 = scipy.io.loadmat('/zi/home/oliver.frank/Desktop/RNN/multitask_BeRNN-main/sc1000')
    #     sc1000_mask = sc1000['mat_zero']
    #     # sc100_mask = sc100['shaefer_rsn']
    #
    #     # info: quadratic mask matrix necessary, maskSize = numberHiddenUnits !
    #     maskSize = sc1000_mask.shape[0]
    #     for i in range(0, maskSize):
    #         for j in range(0, maskSize):
    #             sc1000_mask[i, j] = 1 if sc1000_mask[i, j] > 11 else 0
    #
    #     import numpy as np
    #     count_ones = np.count_nonzero(sc1000_mask[0,:] == 1) # info: 495 hidden units are trained

        # # info: Visualize the structural matrix
        # import matplotlib.pyplot as plt
        #
        # plt.figure(figsize=(8, 8))
        # plt.imshow(sc1000_mask, aspect='auto', cmap='coolwarm')
        # plt.colorbar()
        # plt.title("Visualization of a 1000x1000 ndarray")
        # plt.show()
        #
        # hp['s_mask'] = sc1000_mask
    # elif # fix: Add other structural masks here


    # Build the model
    model = Model(model_dir, hp=hp)

    # Display hp
    for key, val in hp.items():
        print('{:20s} = '.format(key) + str(val))

    # Store results
    log = defaultdict(list)
    log['model_dir'] = model_dir

    # Record time
    t_start = time.time()
    # Count loaded trials/batches
    trialsLoaded = 0

    with tf.Session() as sess:
        if load_dir is not None:
            model.restore(load_dir)  # complete restore
            print('model restored')
        else:
            # Assume everything is restored
            sess.run(tf.global_variables_initializer())

        # Set trainable parameters
        if trainables is None or trainables == 'all':
            var_list = model.var_list  # train everything
        elif trainables == 'input':
            # train all nputs
            var_list = [v for v in model.var_list if ('input' in v.name) and ('rnn' not in v.name)]
        elif trainables == 'rule':
            # train rule inputs only
            var_list = [v for v in model.var_list if 'rule_input' in v.name]
        else:
            raise ValueError('Unknown trainables')
        model.set_optimizer(var_list=var_list)

        # penalty on deviation from initial weight
        if hp['l2_weight_init'] > 0:
            anchor_ws = sess.run(model.weight_list)
            for w, w_val in zip(model.weight_list, anchor_ws):
                model.cost_reg += (hp['l2_weight_init'] * tf.nn.l2_loss(w - w_val))

            model.set_optimizer(var_list=var_list)

        # partial weight training
        # Explanation: In summary, this code introduces a form of partial weight training by applying L2 regularization
        # only to a subset of the weights. The subset is determined by random masking, controlled by the hyperparameter
        # 'p_weight_train'. All weights below the p_weight_train threshold won't be trained in this iteration.
        if ('p_weight_train' in hp and
                (hp['p_weight_train'] is not None) and
                hp['p_weight_train'] < 1.0):
            for w in model.weight_list:
                w_val = sess.run(w)
                w_size = sess.run(tf.size(w))
                w_mask_tmp = np.linspace(0, 1, w_size)
                hp['rng'].shuffle(w_mask_tmp)
                ind_fix = w_mask_tmp > hp['p_weight_train']
                w_mask = np.zeros(w_size, dtype=np.float32)
                w_mask[ind_fix] = 1e-1  # will be squared in l2_loss
                w_mask = tf.constant(w_mask)
                w_mask = tf.reshape(w_mask, w.shape)
                model.cost_reg += tf.nn.l2_loss((w - w_val) * w_mask)
            model.set_optimizer(var_list=var_list)

        step = 0
        if 'WM' in subdir.split('/')[-1]: divider = 4
        else: divider = 2
        while (step * hp['batch_size'])/divider <= max_steps:
            try:
                # Validation
                if step % display_step == 0: # III: Every 500 steps (20000 trials) do the evaluation
                    log['trials'].append(step * hp['batch_size'])
                    log['times'].append(time.time() - t_start)
                    log = do_eval(sess, model, log, hp['rule_trains'],eval_data)
                    elapsed_time = time.time() - t_start  # Calculate elapsed time
                    print(f"Elapsed time after batch number {trialsLoaded}: {elapsed_time:.2f} seconds")
                    # After training
                    total_time = time.time() - t_start
                    print(f"Total training time: {total_time:.2f} seconds")
                    # if log['perf_avg'][-1] > model.hp['target_perf']:
                    # check if minimum performance is above target
                    if log['perf_min'][-1] > model.hp['target_perf']:
                        print('Perf reached the target: {:0.2f}'.format(
                            hp['target_perf']))
                        break

                    # if rich_output:
                    #     display_rich_output(model, sess, step, log, model_dir)

                # Training
                task = hp['rng'].choice(hp['rule_trains'], p=hp['rule_probs'])
                # Generate a random batch of trials; each batch has the same trial length
                mode = 'train'
                x,y,y_loc = Tools.load_trials(task,mode,hp['batch_size'], train_data, False) # y_loc is participantResponse_perfEvalForm

                # info: ################################################################################################
                fixation_steps = Tools.getEpochSteps(y)
                if fixation_steps == None:  # Especially important for the splitted WM trials, as they sometimes have 0 trials in one file (should be fixed by Marc)
                    continue

                # Creat c_mask for current batch
                if hp['loss_type'] == 'lsq':
                    c_mask = np.zeros((y.shape[0], y.shape[1], y.shape[2]), dtype='float32')
                    for i in range(y.shape[1]):
                        # Fixation epoch
                        c_mask[:fixation_steps, i, :] = 1.
                        # Response epoch
                        c_mask[fixation_steps:, i, :] = hp['c_mask_responseValue'] # info: 1 or 5

                    # self.c_mask[:, :, 0] *= self.n_eachring # Fixation is important
                    # c_mask[:, :, 0] *= 2.  # Fixation is important # info: with or without
                    c_mask = c_mask.reshape((y.shape[0]*y.shape[1], y.shape[2]))

                else:
                    c_mask = np.zeros((y.shape[0], y.shape[1]), dtype='float32')
                    for i in range(y.shape[1]):
                        # Fixation epoch
                        c_mask[:fixation_steps, i, :] = 1.
                        # Response epoch
                        c_mask[fixation_steps:, i, :] = hp['c_mask_responseValue'] # info: 1 or 5

                    c_mask = c_mask.reshape((y.shape[0] * y.shape[1],))
                    c_mask /= c_mask.mean()

                # info: ################################################################################################

                trialsLoaded += 1

                # Generating feed_dict.
                feed_dict = Tools.gen_feed_dict(model, x, y, c_mask, hp)
                # print('passed feed_dict Training')
                # print(feed_dict)
                sess.run(model.train_step, feed_dict=feed_dict) # info: Trainables are actualized

                # Get Training performance in a similiar fashion as in do_eval
                clsq_train_tmp = list()
                creg_train_tmp = list()
                perf_train_tmp = list()
                c_lsq_train, c_reg_train, y_hat_train = sess.run([model.cost_lsq, model.cost_reg, model.y_hat], feed_dict=feed_dict)
                perf_train = np.round(np.mean(get_perf(y_hat_train, y_loc)),3) # info: y_loc is participant response as groundTruth
                # print('perf_train   ', perf_train)
                clsq_train_tmp.append(c_lsq_train)
                creg_train_tmp.append(c_reg_train)
                perf_train_tmp.append(perf_train)

                log['cost_train_' + task].append(np.mean(clsq_train_tmp, dtype=np.float64))
                log['creg_train_' + task].append(np.mean(creg_train_tmp, dtype=np.float64))
                log['perf_train_' + task].append(np.mean(perf_train_tmp, dtype=np.float64))

                print('{:15s}'.format(task) +
                      '| train cost {:0.6f}'.format(np.mean(clsq_train_tmp)) +
                      '| train c_reg {:0.6f}'.format(np.mean(c_reg_train)) +
                      '  | train perf {:0.2f}'.format(np.mean(perf_train)))

                step += 1

            except KeyboardInterrupt:
                print("Optimization interrupted by user")
                break

        print("Optimization finished!")

########################################################################################################################
# Train model
########################################################################################################################
if __name__ == '__main__':

    # Define probability of each task being trained
    # rule_prob_map = {"DM": 1,"DM_Anti": 1,"EF": 1,"EF_Anti": 1,"RP": 1,"RP_Anti": 1,"RP_Ctx1": 1,"RP_Ctx2": 1,"WM": 1,"WM_Anti": 1,"WM_Ctx1": 1,"WM_Ctx2": 1}
    rule_prob_map = {"DM": 0, "DM_Anti": 0, "EF": 0, "EF_Anti": 0, "RP": 0, "RP_Anti": 0, "RP_Ctx1": 0, "RP_Ctx2": 0,
                     "WM": 0, "WM_Anti": 1, "WM_Ctx1": 0, "WM_Ctx2": 0}
    taskClass = 'WMAnti'

    for modelNumber in range(2,3):

        monthsConsidered = ['month_3','month_4','month_5']
        chosenData = 'coronly.npy' # 'sysrand.npy' info: don't use script for original data set
        load_dir = None
        for month in monthsConsidered: # attention: You have to delete this if cascade training should be set OFF
            # Adjust variables manually as needed
            model_folder = 'Model'
            participant = 'BeRNN_03'
            model_name = f'{participant}_{taskClass}_{chosenData.split(".")[0]}_32RNNsoftplus_reg5e-5_{month}'

            path = 'C:\\Users\\oliver.frank\\Desktop\\BackUp'  # local
            # path = 'W:\\group_csp\\analyses\\oliver.frank' # fl storage
            # path = '/data' # hitkip cluster
            # path = '/pandora/home/oliver.frank/01_Projects/RNN/multitask_BeRNN-main' # pandora server

            # Define data path for different servers
            preprocessedData_path = os.path.join(path, 'Data', participant, 'PreprocessedData_wResp_ALL')

            # Define model_dir for different servers
            model_dir = os.path.join(f'{path}\\beRNNmodels\\barnaModels\\{participant}_32RNNsoftplus_DM_sequence{modelNumber}', model_name)

            if not os.path.exists(model_dir):
                os.makedirs(model_dir)

            # # Define months taken into account for model training
            # months = model_name.split('_')[-1].split('-')
            # monthsConsidered = []
            # for i in range(int(months[0]), int(months[1]) + 1):
            #     monthsConsidered.append(str(i))

            # Split the data into training and test data -----------------------------------------------------------------------
            # List of the subdirectories
            subdirs = [os.path.join(preprocessedData_path, d) for d in os.listdir(preprocessedData_path) if os.path.isdir(os.path.join(preprocessedData_path, d))]

            # Initialize dictionaries to store training and evaluation data
            train_data = {}
            eval_data = {}

            for subdir in subdirs:
                # Collect all file triplets in the current subdirectory
                file_triplets = []
                for file in os.listdir(subdir):
                    if 'Input' in file and chosenData.split('.')[0] in file: # attention: Delete chosenData if trained on Original data
                        # # III: Exclude files with specific substrings in their names
                        # if any(exclude in file for exclude in ['Randomization', 'Segmentation', 'Mirrored', 'Rotation']):
                        #     continue
                        if not any(exclude in file for exclude in monthsConsidered):
                            continue
                        # if month not in file: # Sort out months which should not be considered; attention: change to this if cascade is run
                        #     continue
                        # Add all necessary files to triplets
                        if not 'WM' in subdir.split('/')[-1]: # attention: don't use '//' for pandora
                            base_name = file.split('Input')[0]
                            input_file = os.path.join(subdir, base_name + 'Input_ORIGINAL_' + chosenData)
                            yloc_file = os.path.join(subdir, base_name + 'yLoc_ORIGINAL_'+ chosenData)
                            output_file = os.path.join(subdir, base_name + 'Output_ORIGINAL_' + chosenData)
                            file_triplets.append((input_file, yloc_file, output_file))
                        else:
                            base_name = file.split('Input')[0]
                            fileEnd = '_' + file.split('_')[-1]
                            input_file = os.path.join(subdir, base_name + 'Input_' + chosenData.split('.')[0] + fileEnd)
                            yloc_file = os.path.join(subdir, base_name + 'yLoc_' + chosenData.split('.')[0] + fileEnd)
                            output_file = os.path.join(subdir, base_name + 'Output_' + chosenData.split('.')[0] + fileEnd)
                            file_triplets.append((input_file, yloc_file, output_file))
                        # print(input_file)
                    # Split the file triplets
                    train_files, eval_files = split_files(file_triplets)

                    # Store the results in the dictionaries
                    train_data[subdir] = train_files
                    eval_data[subdir] = eval_files

            # Start Training ---------------------------------------------------------------------------------------------------
            train(model_dir=model_dir, rule_prob_map=rule_prob_map, train_data = train_data, eval_data = eval_data, subdir = subdir, load_dir = load_dir)

            load_dir = model_dir # attention: Comment out if no Cascade training should be applied


