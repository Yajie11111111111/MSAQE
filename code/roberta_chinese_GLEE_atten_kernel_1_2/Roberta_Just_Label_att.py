# coding: utf-8

import os
os.environ['CUDA_VISIBLE_DEVICES'] = '7'
import torch
from sklearn.metrics import f1_score, accuracy_score, hamming_loss, classification_report, jaccard_score, classification_report
from torch.utils.data import TensorDataset, DataLoader, RandomSampler, SequentialSampler
from transformers import AutoTokenizer, AutoModelForSequenceClassification,\
AdamW, get_linear_schedule_with_warmup
from BertCNNClassifier_att import BertCNNClassifier_att
import numpy as np
import pandas as pd
import random
from tqdm import trange
import yaml
import argparse
from util_loss import ResampleLoss
import warnings
warnings.filterwarnings("ignore", category=UserWarning)

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu') # Defines the device variable.

def seed(seed=10):
    torch.manual_seed(seed) 
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    random.seed(seed) 
    np.random.seed(seed) 

def initialise_tokenizer(modelname):
    if modelname == 'roberta_chinese_GLEE_atten_kernel_1_2':
        BERT_CHI_EXT_dir = '/data/0WYJ/newdata_wyj/CMLTES_codes/multi_class/ROBERTA_chinese_wwm-ext' 
        tokenizer = AutoTokenizer.from_pretrained(BERT_CHI_EXT_dir)
    return tokenizer

def initialise_optimizer(model, num_training_steps):

    optimizer = AdamW(model.parameters(), lr=float(args['learning_rate'])) 
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=100, num_training_steps=num_training_steps)

    return optimizer, scheduler

def initialise_model(modelname):
    if modelname == 'roberta_chinese_GLEE_atten_kernel_1_2':
        BERT_CHI_EXT_dir = '/data/0WYJ/newdata_wyj/CMLTES_codes/multi_class/ROBERTA_chinese_wwm-ext'
        tokenizer = AutoTokenizer.from_pretrained(BERT_CHI_EXT_dir)
        model = AutoModelForSequenceClassification.from_pretrained(BERT_CHI_EXT_dir, num_labels=args['num_labels']) # Loading Models.
        model.config.problem_type = 'multi_label_classification'
    return model, tokenizer

def load_model(save_path):
    
    if args['modelname'] == 'roberta_chinese_GLEE_atten_kernel_1_2':
        model = BertCNNClassifier_att(num_labels=args['num_labels'], mlp_size=args['mlp_size'], 
                                      bert_output_dim=768, conv_out_channels=256, kernel_sizes=[1, 2])
        model.to(device)
        
        tokenizer_path = '/data/0WYJ/newdata_wyj/CMLTES_codes/multi_class/ROBERTA_chinese_wwm-ext' 
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)

    checkpoint = torch.load(save_path) # Load the parameters of the model.
    model_state_dict = checkpoint['state_dict'] # Get the parameters of the model.
    model.load_state_dict(model_state_dict) # Load the parameters of the model.
    
    return model, tokenizer

def get_dataloader(path, tokenizer, train:bool): 
    text, labels = get_data(path, tokenizer) # Call the get_data method to load the dataset and store the text data and labels data in the text and labels variables respectively.
    dataloader = new_dataloader(text, labels, train) # Call the dataloader method to get the data loader and store it in the dataloader variable.
    return dataloader

def get_data(path, tokenizer):
    
    text, labels = load_dataset(path) # Call the load_dataset method to load the dataset and store the text data and labels data in the text and labels variables respectively.
    #text = tokenizer(text, padding=True, truncation=True,  max_length=max_length, return_tensors='pt') 
    text = tokenizer(text, padding='max_length', truncation=True, return_tensors='pt', max_length=args['max_length']) 
    text = text.to(device)  # move text to GPU *
    return text, labels

def new_dataloader(text, labels, train:bool): # This code defines a method called dataloader to get the data loader.
    data = TensorDataset(text['input_ids'], text['attention_mask'], torch.tensor(labels)) 
    
    if train:
        sampler = RandomSampler(data) # Create a random sampler.
        dataloader = DataLoader(data, # Create a data loader.
                                sampler=sampler, # A random sampler was used.
                                batch_size=args['batch_size']) # Set the batch size.
    else:
        sampler = SequentialSampler(data) # Creates a sequential sampler.
        dataloader = DataLoader(data, # Create a data loader.
                                sampler=sampler, # Sequential samplers are used.
                                batch_size=args['batch_size']) # Set the batch size.
        
    return dataloader

def load_dataset(path): # This code defines a method called load_dataset for loading datasets.
    df = pd.read_csv(path, index_col=False) # Use the pandas library to read the dataset. and store it in the DataFrame object df.
    text = df['description'].tolist()  # Convert the ‘temp’ column in the DataFrame object df to a list and store it in the text variable.
    # Here temp stores the text of the original tweet minus the special symbols.
    label = df[['label1', 'label2', 'label3','label4','label5','label6','label7','label8']].values.tolist()
    # print(label[0]) # Print the first of the labels
    label = get_one_hot_encode(label)
    return text, label

def get_one_hot_encode(labels):
    unique_label = np.array(['旅游交通', '游览', '旅游安全', '卫生', '邮电', '旅游购物', '经营管理', '资源和环境保护']) 
    
    one_hot = np.zeros((len(labels), args['num_labels'])) # Create an all-zero matrix with the number of rows as the number of labels and the number of columns as the number of labels.
    
    for i in range(len(labels)): # Iterate through the list of tags.
        for j in range(8): # Iterates through each tag in the tag list.
            try: # Try converting the tag to one-hot encoding.
                idx = np.where(unique_label == labels[i][j])[0][0] # Gets the index of the tag in the list of tags.
                one_hot[i][idx] = 1 # Set the corresponding position in the one-hot code to 1.
            except:   # If the label is not in the label list, it is skipped.
                continue 
            
    return one_hot

def save_model(epoch, model, model_save_dir):
    
    checkpoint = {'epoch': epoch, \
                    'state_dict': model.state_dict()
                    }
    torch.save(checkpoint, model_save_dir)
    # print("Saving model at iteration {}".format(epoch)) # Prints information about the saved model.

def main(args):
    
    seed()
    
    macro_scores = [] # Used to store macro-averaged F1 scores for each model and batch size configuration.
    micro_scores = [] # Used to store micro-averaged F1 scores for each model and batch size configuration.
    accuracy_scores = [] # Used to store the accuracy of each model and batch size configuration.
    weighted_f1_scores = [] #  Used to store weighted F1 scores for each model and batch size configuration.
    jaccard_scores = [] # Used to store Jaccard scores for each model and batch size configuration.
    hamming_losses = [] # Used to store Hamming losses for each model and batch size configuration.
    
    train_loss_set = [] # Used to store the training loss for each epoch.
    valid_loss_set = [] # Used to store the validation loss for each epoch.

    best_macro = None # Used to store the best macro average F1 score.

    tokenizer = initialise_tokenizer(args['modelname'])

    model = BertCNNClassifier_att(num_labels=args['num_labels'], mlp_size=args['mlp_size'])

    model = model.to(device)

    num_training_steps = args['num_epochs'] * (args['num_samples'] // args['batch_size']) #Total training steps

    optimizer, scheduler = initialise_optimizer(model, num_training_steps)

    loss_func = ResampleLoss(reweight_func='CB', loss_weight=10.0,
                             focal=dict(focal=True, alpha=0.5, gamma=2),
                             logit_reg=dict(),
                             CB_loss=dict(CB_beta=0.9, CB_mode='by_class'),
                             class_freq=args['class_freq'], train_num=args['num_samples'])
    

    train_dataloader = get_dataloader(args['traincsvpath'], tokenizer, train=True) # Training data loader.
    valid_dataloader = get_dataloader(args['valcsvpath'], tokenizer, train=False) # Validate the data loader.

    for actual_epoch in trange(args['num_epochs'], desc="Epoch"):
        
        epoch_train_loss = train(model, train_dataloader, optimizer, scheduler, loss_func, actual_epoch)   
        train_loss_set.append(epoch_train_loss) # Add the training loss of the current epoch to train_loss_set.
        
        epoch_eval_loss, micro, macro, accuracy, weighted_f1, jaccard, hl = validate(model, valid_dataloader, loss_func, actual_epoch) # Evaluate the model on the validation set.
        valid_loss_set.append(epoch_eval_loss) # Add the assessed loss value to the list.

        micro_scores.append(micro)
        macro_scores.append(macro)
        accuracy_scores.append(accuracy)
        weighted_f1_scores.append(weighted_f1)
        jaccard_scores.append(jaccard)
        hamming_losses.append(hl)
        
        if best_macro == None : 
            best_macro = macro
            save_model(actual_epoch, model, args['model_save_dir'] + '/best_macro_model_att_large.pt')
        else:
            if macro > best_macro:
                best_macro = macro
                save_model(actual_epoch, model, args['model_save_dir'] + '/best_macro_model_att_large.pt')


def train(model, train_dataloader, optimizer, scheduler, loss_func, actual_epoch):
    
    model.train() # Set the model into training mode by calling the train() method.
    
    tr_loss = 0 # Used to store the training loss for the current epoch.
    num_train_samples = 0 # The number of training samples used to store the current epoch.
    
    for _, batch in enumerate(train_dataloader):  # Use the enumerate function to traverse the batch data in the training data loader (train_dataloader).
        
        batch = tuple(t.to(device) for t in batch) # Move batch data to the GPU.
        
        b_input_ids, b_input_mask, b_labels = batch # Unpacks batch data into input IDs, input masks, and labels.
    
        optimizer.zero_grad()
        logits = model(b_input_ids, attention_mask=b_input_mask)
        loss = loss_func(logits.view(-1,args['num_labels']), b_labels.type_as(logits).view(-1,args['num_labels']))
        
        tr_loss += loss.item()
        
        num_train_samples += b_labels.size(0) # Adds the number of samples in the batch to num_train_samples. Accumulate the number of samples
        
        loss.backward() # Calculate the gradient of the loss.        
        optimizer.step() # Update the model parameters.
        scheduler.step() # Updated learning rates.
        
    epoch_train_loss = tr_loss / num_train_samples # Calculate the training loss for the current epoch.

    # print("\nTrain loss after Epoch {} : {}".format(actual_epoch, epoch_train_loss)) # Prints the training loss for the current epoch.
    
    return epoch_train_loss


@torch.no_grad()
def validate(model, valid_dataloader, loss_func, epoch, threshold=0.5):

    model.eval()   # Set the model to evaluation mode by calling the eval() method. 

    eval_loss = 0 # Create a variable that will be used to accumulate the variables for evaluating loss values.
    num_eval_samples = 0  # Create a variable for the cumulative assessment of the sample size variable.
    
    pred_labels = [] # Create an empty list for storing prediction labels.
    true_labels = [] # Creates an empty list to store the original labels.
    
    for _, batch in enumerate(valid_dataloader): # Use the enumerate function to iterate through the batch data in the validation data loader.
        
        batch = tuple(t.to(device) for t in batch) # Move batch data to the GPU.
        b_input_ids, b_input_mask, b_labels = batch # Get batch data.
        
        logits = model(b_input_ids, attention_mask=b_input_mask)  # Get logits directly                        
        loss = loss_func(logits.view(-1,args['num_labels']), 
                                b_labels.type_as(logits).view(-1,args['num_labels'])) # Calculate the value of the loss.
            
        pred_label = torch.sigmoid(logits) # Use the sigmoid function to convert predictions to probability values.
        pred_label = pred_label.to('cpu').numpy() # Move the prediction label to the CPU.
        b_labels = b_labels.to('cpu').numpy() # Move the original label to the CPU.
            
        pred_labels.append(pred_label) # Add the prediction tag to the list.
        true_labels.append(b_labels) # Add the original tag to the list.

        eval_loss += loss.item() 
        num_eval_samples += b_labels.shape[0]

    epoch_eval_loss = eval_loss/num_eval_samples # Calculate the value of the assessed loss.

    # print("Val loss after Epoch {} : {}".format(epoch, epoch_eval_loss)) # Prints the training loss for the current epoch.        

    pred_labels = [item for sublist in pred_labels for item in sublist] # Convert prediction labels to a one-dimensional list.
    true_labels = [item for sublist in true_labels for item in sublist] # Converts raw labels to a one-dimensional list.
    
    pred_bools = [pl>threshold for pl in pred_labels]
    true_bools = [tl==1 for tl in true_labels]
    
    micro = f1_score(true_bools, pred_bools, average='micro')
    macro = f1_score(true_bools, pred_bools, average='macro')
    accuracy = accuracy_score(true_bools, pred_bools)
    weighted_f1 = f1_score(true_bools, pred_bools, average='weighted') 
    jaccard = jaccard_score(true_bools, pred_bools, average='weighted') 
    hl = hamming_loss(true_bools, pred_bools)

    # print("Valid loss: {}".format(epoch_eval_loss))
    # print(f"Micro Validaton Score: ", micro)
    # print(f"Macro Validaton Score: ", macro)
    # print(f"Accuracy Validation Score: {accuracy}")
    # print(f"Weighted F1 Validaton Score: ", weighted_f1) 
    # print(f"Jaccard Validaton Score: ", jaccard)
    # print(f"Hamming loss: ", hl) 

    return epoch_eval_loss, micro, macro, accuracy, weighted_f1, jaccard, hl


@torch.no_grad()
def test(save_path): # Define the test function, which is used to evaluate the model on a test set.
        
    pred_labels = [] # Define empty list for storing prediction labels.
    true_labels = [] # Define empty list for storing real labels.
    
    model, tokenizer = load_model(save_path) # Loading Models.
    model = model.to(device)     # Moves the model to the specified device.
    model.eval()

    test_dataloader = get_dataloader(args['testcsvpath'], tokenizer, train=False) # Test Data Loader.
    

    # unique_label = np.array(['旅游交通', '游览', '旅游安全', '卫生', '邮电', '旅游购物', '经营管理', '资源和环境保护'])

    for idx, batch in enumerate(test_dataloader): # The data loader that traverses the test set.
        batch = tuple(t.to(device) for t in batch) # Moves data to the specified device.
        b_input_ids, b_input_mask, b_labels = batch # Get input data.
        
        logits = model(b_input_ids, attention_mask=b_input_mask)  # Get logits directly
        pred_label = torch.sigmoid(logits) # Perform a sigmoid operation on the output of the model.
        # print(pred_label)
            
        pred_label = pred_label.to('cpu').numpy() # Move the prediction label to the CPU.
        b_labels = b_labels.to('cpu').numpy() # Move the real label to the CPU.
        
        pred_labels.append(pred_label) # Add prediction labels to pred_labels.
        true_labels.append(b_labels) # Add true labels to true_labels.

        # Decode the predicted labels for each sample.
        # for i, label_scores in enumerate(pred_label):
        #     label_indices = np.where(label_scores > 0.5)[0]  # The threshold is set to 0.5.
        #     predicted_labels = unique_label[label_indices]  # Gets the name of the predicted label.
        #     print(f"Sample {idx * test_dataloader.batch_size + i} predicting label is: {predicted_labels}")  # Print the prediction labels for the samples.
    
    y_pred = pred_labels #Assigns the prediction label to y_pred.
    y_true = true_labels #Assign the true label to y_true.
    
    pred_labels = [item for sublist in pred_labels for item in sublist] # Convert prediction labels to a one-dimensional list.
    true_labels = [item for sublist in true_labels for item in sublist] # Convert real labels to one-dimensional lists.
    
    # single_true, multi_true, single_pred, multi_pred, true, predictions = metric_calculation(y_true, y_pred)

    predictions = [] # Define the predictions variable.
    for i in y_pred: # Iterate over y_pred.
        for j in i: # Iterate over i.
            pred = [] # Define the pred variable.
            for k in j: # Iterate over j.
                if k > 0.5: # If k is greater than 0.5.
                    pred.append(1) # Add 1 to pred.
                else: 
                    pred.append(0) # Add 0 to pred.
            predictions.append(pred) # Adds pred to predictions.

    true = [] # Define the true variable.
    for i in y_true: # Iterate over y_true.
        for j in i:  # Iterate over i.
            true_ = [] # Define the true_ variable.
            for k in j: # Iterate over j.
                true_.append(int(k)) # Add int(k) to true_.
            true.append(true_) # Add true_ to true.
    # print(f"Macro F1 Based: Macro F1: {macro}, Micro F1: {micro}, weighted_f1: {weighted_f1}, jaccard: {jaccard}, hamming loss:{hl} and Accuracy: {accuracy}") #Performance metrics for printing models.
    
    ## Calculation Acccuracy:
    threshold = 0.50
    pred_bools = [pl>threshold for pl in pred_labels] # Converts prediction labels to boolean values.
    true_bools = [tl==1 for tl in true_labels] # Converts real labels to boolean values.
    
    micro = f1_score(true_bools, pred_bools, average='micro') # Calculate the micro F1 score.
    accuracy = accuracy_score(true_bools, pred_bools) # Calculate the accuracy.
    macro = f1_score(true_bools, pred_bools, average='macro') # Calculate the macro F1 score.
    weighted_f1 = f1_score(true_bools, pred_bools, average='weighted') 
    jaccard = jaccard_score(true_bools, pred_bools, average='weighted') 
    hl = hamming_loss(true_bools, pred_bools)
    
    print(f"TEST FOR " + args['modelname'] + " and Batch Size" + str(args['batch_size']))

    print(f"Macro F1 Based: Macro F1: {macro}, Micro F1: {micro}, weighted_f1: {weighted_f1}, jaccard: {jaccard},hamming loss:{hl} and Accuracy: {accuracy}") # Printed model performance metrics.


def metric_calculation(y_true, y_pred): # Define the metric_calculation function to calculate the evaluation metrics.
    single_label_indices = [] # Define the single_label_indices variable.
    multi_label_indices = [] # Define the multi_label_indices variable.

    true = [] # Define the true variable.
    for i in y_true: # Traverse y_true.
        for j in i: # Iterate over i.
            true.append(list(j.astype('long'))) # Convert j to long and add to true.

    for i in range(len(true)): # Iterate over true.
        if np.sum(true[i]) > 1: # If the sum of true[i] is greater than 1.
            multi_label_indices.append(i) # Add i to multi_label_indices.
        else:
            single_label_indices.append(i) # Add i to single_label_indices.

    single_true = [true[idx] for idx in single_label_indices] # Define the single_true variable.
    multi_true = [true[idx] for idx in multi_label_indices] # Define the multi_true variable.

    predictions = [] # Define the predictions variable.
    for i in y_pred: # Iterate over y_pred.
        for j in i: # Iterate over i.
            pred = [] # Define the pred variable.
            for k in j: # Iterate over j.
                if k > 0.5: # If k is greater than 0.5.
                    pred.append(1) # Add 1 to pred.
                else:  # If k is not greater than 0.5.
                    pred.append(0) # Add 0 to pred.
            predictions.append(pred) # Adds pred to predictions.

    single_pred = [predictions[idx] for idx in single_label_indices] # Define the single_pred variable.
    multi_pred = [predictions[idx] for idx in multi_label_indices] # Define the multi_pred variable.
    
    print('Jacc Single label: ', jaccard_score(single_true, single_pred, average='samples')) # Prints a prompt message.
    print('Jacc Multi label: ', jaccard_score(multi_true, multi_pred, average='samples')) # Prints a prompt message.
    print('Jacc Weighted Single label: ', jaccard_score(single_true, single_pred, average='weighted')) # Prints a prompt message.
    print('Jacc Weighted Multi label: ', jaccard_score(multi_true, multi_pred, average='weighted')) # Prints a prompt message.
    print('Jacc Samples Score: ', jaccard_score(true, predictions, average='samples')) # Calculates the true and predicted jaccard_score.
    print('\n')
    NUM_NONE = 0
    for j in predictions: # Iterate over predictions.
        if np.sum(j) == 0: # If the sum of j is 0.
            NUM_NONE += 1 # NUM_NONE plus 1.
    print(NUM_NONE) # Prints NUM_NONE.
    print('\n')
    print(classification_report(true, predictions)) # Prints a prompt message.
    print('\n')
    print('F1-weighted Score: ', f1_score(true, predictions, average='weighted')) # Prints a prompt message.
    return single_true, multi_true, single_pred, multi_pred, true, predictions  # Returns single_true, multi_true, single_pred, multi_pred, true, predictions.


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('-args', help="priority", type=bool, required=False, default=True)
    parser.add_argument('-config', help="configuration file *.yml", type=str, required=False, default='/data/0WYJ/newdata_wyj/CMLTES_codes/experiment/roberta_chinese_GLEE_atten_kernel_1_2/config.yml')
    parser.add_argument('-mode', help="train&test", type=str, required=False, default='test')
    parser.add_argument('-scale', help="large/small", type=str, required=True, default='large')
    args = parser.parse_args()
    
    if args.args:  # args priority is higher than yaml
        opt = yaml.load(open(args.config), Loader=yaml.FullLoader)
        opt.update(vars(args))
        args = opt
    else:  # yaml priority is higher than args
        opt = vars(args)
        args = yaml.load(open(args.config), Loader=yaml.FullLoader)
        opt.update(args)
        args = opt

    df = pd.read_csv(args['traincsvpath']) # Read the traincsvpath file.
    args['num_samples'] = len(df) # Define the num_samples variable.
    df_val = pd.read_csv(args['valcsvpath'])
    args['num_samples_val'] = len(df_val)
    df_test = pd.read_csv(args['testcsvpath'])
    args['num_samples_test'] = len(df_test)
    args['model_save_dir'] =  os.path.join(args['filename'], 'models', args['modelname'], str(args['batch_size'])) 
    
    if args['scale'] == "large":
        args['class_freq'] = [53262, 204846, 10478, 164656, 218, 5246, 230499, 188900]
        args['ckpt_path'] = args['model_save_dir'] + '/best_macro_model_att_large.pt'

        args['traincsvpath'] = '/data/0WYJ/newdata_wyj/CMLTES_codes/data/large_dataset_with_label/trainset.csv' # Defines the traincsvpath variable.
        args['valcsvpath'] = '/data/0WYJ/newdata_wyj/CMLTES_codes/data/large_dataset_with_label/valset.csv' # Defines the valcsvpath variable.
        args['testcsvpath'] = '/data/0WYJ/newdata_wyj/CMLTES_codes/data/large_dataset_with_label/testset.csv' # Defines the testcsvpath variable.

    elif args['scale'] == "small":
        args['class_freq'] = [3839, 12747, 745, 9243, 4, 163, 13745, 12088]  # Number of samples in each category in the dataset
        args['ckpt_path'] = args['model_save_dir'] + '/best_macro_model_att_small.pt'

        args['traincsvpath'] = '/data/0WYJ/newdata_wyj/CMLTES_codes/data/small_with_label/small_transfer_trainset_label_chinese.csv' # Defines the traincsvpath variable.
        args['valcsvpath'] = '/data/0WYJ/newdata_wyj/CMLTES_codes/data/small_with_label/small_transfer_valset_label_chinese.csv' # Defines the valcsvpath variable.
        args['testcsvpath'] = '/data/0WYJ/newdata_wyj/CMLTES_codes/data/small_with_label/small_transfer_testset_label_chinese.csv' # Defines the testcsvpath variable.
    
    args['d_model'] = 512
    args['d_ff'] = 2048   

    if not os.path.exists(args['model_save_dir']): 
        os.makedirs(args['model_save_dir']) 

    if args['mode'] == 'train':
        main(args)
        
    elif args['mode'] == 'test':
        test(args['ckpt_path'])