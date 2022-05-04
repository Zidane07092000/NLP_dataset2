# -*- coding: utf-8 -*-
"""NLP_Shared_Task_Final.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1t6U5GZSdZ0LSG_i7e5EY7OUmYjkrEV6A
"""

import transformers
from transformers import set_seed
#set_seed(42)
print(transformers.__version__)

# Change the below parameters accordingly for different models

#torch.manual_seed(42)

model_type = "large"
model_checkpoint = "bert-base-multilingual-cased"
TRAIN = True
dataset_name = "tydiqa"
task_type = "secondary_task"
batch_size = 32
labelled_data_split = 0.8
num_of_runs = 5

from datasets import load_dataset, load_metric, DatasetDict, Dataset, concatenate_datasets
import pyarrow as pa
import pyarrow.dataset as ds
import pandas as pd
import numpy as np

original_datasets = load_dataset(dataset_name, task_type)

# original_datasets

# original_datasets["train"][0]

# extracting english, bengali, and telugu from original_datasets
if model_type == "small":
    datasets = original_datasets.filter(lambda example: example["id"].startswith(('english', 'bengali', 'telugu')))
    print("SMALL")
else:
    datasets = original_datasets
    print("LARGE")

from datasets import ClassLabel, Sequence, Dataset
import random
import pandas as pd
from IPython.display import display, HTML

def show_random_elements(dataset, num_examples=10):
    assert num_examples <= len(dataset), "Can't pick more elements than there are in the dataset."
    picks = []
    for _ in range(num_examples):
        pick = random.randint(0, len(dataset)-1)
        while pick in picks:
            pick = random.randint(0, len(dataset)-1)
        picks.append(pick)
    
    df = pd.DataFrame(dataset[picks])
    for column, typ in dataset.features.items():
        if isinstance(typ, ClassLabel):
            df[column] = df[column].transform(lambda i: typ.names[i])
        elif isinstance(typ, Sequence) and isinstance(typ.feature, ClassLabel):
            df[column] = df[column].transform(lambda x: [typ.feature.names[i] for i in x])
    display(HTML(df.to_html()))

show_random_elements(datasets["train"], num_examples=10)

from transformers import AutoTokenizer
    
tokenizer = AutoTokenizer.from_pretrained(model_checkpoint)

import transformers
assert isinstance(tokenizer, transformers.PreTrainedTokenizerFast)

max_length = 384 # The maximum length of a feature (question and context)
doc_stride = 128 # The authorized overlap between two part of the context when splitting it is needed.

pad_on_right = tokenizer.padding_side == "right"

def prepare_train_features(examples):
    # Some of the questions have lots of whitespace on the left, which is not useful and will make the
    # truncation of the context fail (the tokenized question will take a lots of space). So we remove that
    # left whitespace
    examples["question"] = [q.lstrip() for q in examples["question"]]

    # Tokenize our examples with truncation and padding, but keep the overflows using a stride. This results
    # in one example possible giving several features when a context is long, each of those features having a
    # context that overlaps a bit the context of the previous feature.
    tokenized_examples = tokenizer(
        examples["question" if pad_on_right else "context"],
        examples["context" if pad_on_right else "question"],
        truncation="only_second" if pad_on_right else "only_first",
        max_length=max_length,
        stride=doc_stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        padding="max_length",
    )

    # Since one example might give us several features if it has a long context, we need a map from a feature to
    # its corresponding example. This key gives us just that.
    sample_mapping = tokenized_examples.pop("overflow_to_sample_mapping")
    # The offset mappings will give us a map from token to character position in the original context. This will
    # help us compute the start_positions and end_positions.
    offset_mapping = tokenized_examples.pop("offset_mapping")

    # Let's label those examples!
    tokenized_examples["start_positions"] = []
    tokenized_examples["end_positions"] = []

    for i, offsets in enumerate(offset_mapping):
        # We will label impossible answers with the index of the CLS token.
        input_ids = tokenized_examples["input_ids"][i]
        cls_index = input_ids.index(tokenizer.cls_token_id)

        # Grab the sequence corresponding to that example (to know what is the context and what is the question).
        sequence_ids = tokenized_examples.sequence_ids(i)

        # One example can give several spans, this is the index of the example containing this span of text.
        sample_index = sample_mapping[i]
        answers = examples["answers"][sample_index]
        # If no answers are given, set the cls_index as answer.
        if len(answers["answer_start"]) == 0:
            tokenized_examples["start_positions"].append(cls_index)
            tokenized_examples["end_positions"].append(cls_index)
        else:
            # Start/end character index of the answer in the text.
            start_char = answers["answer_start"][0]
            end_char = start_char + len(answers["text"][0])

            # Start token index of the current span in the text.
            token_start_index = 0
            while sequence_ids[token_start_index] != (1 if pad_on_right else 0):
                token_start_index += 1

            # End token index of the current span in the text.
            token_end_index = len(input_ids) - 1
            while sequence_ids[token_end_index] != (1 if pad_on_right else 0):
                token_end_index -= 1

            # Detect if the answer is out of the span (in which case this feature is labeled with the CLS index).
            if not (offsets[token_start_index][0] <= start_char and offsets[token_end_index][1] >= end_char):
                tokenized_examples["start_positions"].append(cls_index)
                tokenized_examples["end_positions"].append(cls_index)
            else:
                # Otherwise move the token_start_index and token_end_index to the two ends of the answer.
                # Note: we could go after the last offset if the answer is the last word (edge case).
                while token_start_index < len(offsets) and offsets[token_start_index][0] <= start_char:
                    token_start_index += 1
                tokenized_examples["start_positions"].append(token_start_index - 1)
                while offsets[token_end_index][1] >= end_char:
                    token_end_index -= 1
                tokenized_examples["end_positions"].append(token_end_index + 1)

    return tokenized_examples

# datasets

# type(datasets["train"])

# Unbiased Splitting

all_languages = []
for id in datasets["train"]["id"]:
    x = id.partition("-")
    if x[0] not in all_languages:
        all_languages.append(x[0])
print(all_languages)

all_languages_labelled = {}
all_languages_unlabelled = {}
for lang in all_languages:
    temp_dataset = original_datasets.filter(lambda example: example["id"].startswith((lang)))
    df = pd.DataFrame.from_dict(temp_dataset["train"])
    msk = np.random.rand(len(df)) < labelled_data_split
    all_languages_labelled[lang] = Dataset(pa.Table.from_pandas(df[msk])).map(remove_columns=["__index_level_0__"])
    all_languages_unlabelled[lang] = Dataset(pa.Table.from_pandas(df[~msk])).map(remove_columns=["__index_level_0__"])

labelled_datasets = DatasetDict({"train": concatenate_datasets([all_languages_labelled[lang] for lang in all_languages_labelled.keys()]), "validation": original_datasets["validation"]})
unlabelled_datasets = DatasetDict({"train": concatenate_datasets([all_languages_unlabelled[lang] for lang in all_languages_unlabelled.keys()]), "validation": original_datasets["validation"]})

# # Biased Splitting

# Lsize = int(labelled_data_split*len(datasets["train"]))

# print(datasets)
# #print(type(datasets) + " " + type(datasets["train"]) + type(datasets["validation"]))

# LABELLED = datasets["train"][:Lsize] # dict
# UNLABELLED = datasets["train"][Lsize:] # dict

# df_labelled = pd.DataFrame.from_dict(LABELLED) # convert to df
# hg_labelled = Dataset(pa.Table.from_pandas(df_labelled)) # convert to datasets.arrow_dataset.Dataset

# df_unlabelled = pd.DataFrame.from_dict(UNLABELLED) # convert to df
# hg_unlabelled = Dataset(pa.Table.from_pandas(df_unlabelled)) # convert to datasets.arrow_dataset.Dataset

# labelled_datasets = DatasetDict({"train":hg_labelled, "validation":original_datasets["validation"]})
# print(labelled_datasets)
# #print(type(labelled_datasets) + " " + type(labelled_datasets["train"]) + type(labelled_datasets["validation"]))

# unlabelled_datasets = DatasetDict({"train":hg_unlabelled, "validation":original_datasets["validation"]})
# print(unlabelled_datasets)
# #print(type(unlabelled_datasets) + " " + type(unlabelled_datasets["train"]) + type(unlabelled_datasets["validation"]))

# # merging
# MERGED = concatenate_datasets([labelled_datasets["train"], unlabelled_datasets["train"]])
# merged_datasets = DatasetDict({"train":MERGED, "validation":original_datasets["validation"]})
# print(merged_datasets)
# #print(type(merged_datasets) + " " + type(merged_datasets["train"]) + type(merged_datasets["validation"]))

tokenized_datasets = labelled_datasets.map(prepare_train_features, batched=True, remove_columns=labelled_datasets["train"].column_names)

# tokenized_datasets

from transformers import AutoModelForQuestionAnswering, TrainingArguments, Trainer

model = AutoModelForQuestionAnswering.from_pretrained(model_checkpoint)

model_name = model_checkpoint.split("/")[-1]
args = TrainingArguments(
    f"{model_name}-finetuned-tydiqa",
    evaluation_strategy = "epoch",
    learning_rate=2e-5,
    per_device_train_batch_size=batch_size,
    per_device_eval_batch_size=batch_size,
    num_train_epochs=3,
    weight_decay=0.01,
    save_steps=20000
)

from transformers import default_data_collator

data_collator = default_data_collator

global trainer
trainer = Trainer(
    model,
    args,
    train_dataset=tokenized_datasets["train"],
    eval_dataset=tokenized_datasets["validation"],
    data_collator=data_collator,
    tokenizer=tokenizer,
)

if TRAIN:
    trainer.train()

if TRAIN:
    trainer.save_model("f1")

def prepare_validation_features(examples):
    # Some of the questions have lots of whitespace on the left, which is not useful and will make the
    # truncation of the context fail (the tokenized question will take a lots of space). So we remove that
    # left whitespace
    examples["question"] = [q.lstrip() for q in examples["question"]]

    # Tokenize our examples with truncation and maybe padding, but keep the overflows using a stride. This results
    # in one example possible giving several features when a context is long, each of those features having a
    # context that overlaps a bit the context of the previous feature.
    tokenized_examples = tokenizer(
        examples["question" if pad_on_right else "context"],
        examples["context" if pad_on_right else "question"],
        truncation="only_second" if pad_on_right else "only_first",
        max_length=max_length,
        stride=doc_stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        padding="max_length",
    )

    # Since one example might give us several features if it has a long context, we need a map from a feature to
    # its corresponding example. This key gives us just that.
    sample_mapping = tokenized_examples.pop("overflow_to_sample_mapping")

    # We keep the example_id that gave us this feature and we will store the offset mappings.
    tokenized_examples["example_id"] = []

    for i in range(len(tokenized_examples["input_ids"])):
        # Grab the sequence corresponding to that example (to know what is the context and what is the question).
        sequence_ids = tokenized_examples.sequence_ids(i)
        context_index = 1 if pad_on_right else 0

        # One example can give several spans, this is the index of the example containing this span of text.
        sample_index = sample_mapping[i]
        tokenized_examples["example_id"].append(examples["id"][sample_index])

        # Set to None the offset_mapping that are not part of the context so it's easy to determine if a token
        # position is part of the context or not.
        tokenized_examples["offset_mapping"][i] = [
            (o if sequence_ids[k] == context_index else None)
            for k, o in enumerate(tokenized_examples["offset_mapping"][i])
        ]

    return tokenized_examples

from tqdm.auto import tqdm
import collections

def postprocess_qa_predictions(examples, features, raw_predictions, n_best_size = 20, max_answer_length = 50):
    all_start_logits, all_end_logits = raw_predictions
    # Build a map example to its corresponding features.
    example_id_to_index = {k: i for i, k in enumerate(examples["id"])}
    features_per_example = collections.defaultdict(list)
    for i, feature in enumerate(features):
        features_per_example[example_id_to_index[feature["example_id"]]].append(i)

    # The dictionaries we have to fill.
    predictions = collections.OrderedDict()

    # Logging.
    print(f"Post-processing {len(examples)} example predictions split into {len(features)} features.")

    # Let's loop over all the examples!
    for example_index, example in enumerate(tqdm(examples)):
        # Those are the indices of the features associated to the current example.
        feature_indices = features_per_example[example_index]

        min_null_score = None
        valid_answers = []
        
        context = example["context"]
        # Looping through all the features associated to the current example.
        for feature_index in feature_indices:
            # We grab the predictions of the model for this feature.
            start_logits = all_start_logits[feature_index]
            end_logits = all_end_logits[feature_index]
            # This is what will allow us to map some the positions in our logits to span of texts in the original
            # context.
            offset_mapping = features[feature_index]["offset_mapping"]

            # Update minimum null prediction.
            cls_index = features[feature_index]["input_ids"].index(tokenizer.cls_token_id)
            feature_null_score = start_logits[cls_index] + end_logits[cls_index]
            if min_null_score is None or min_null_score < feature_null_score:
                min_null_score = feature_null_score

            # Go through all possibilities for the `n_best_size` greater start and end logits.
            start_indexes = np.argsort(start_logits)[-1 : -n_best_size - 1 : -1].tolist()
            end_indexes = np.argsort(end_logits)[-1 : -n_best_size - 1 : -1].tolist()
            for start_index in start_indexes:
                for end_index in end_indexes:
                    # Don't consider out-of-scope answers, either because the indices are out of bounds or correspond
                    # to part of the input_ids that are not in the context.
                    if (
                        start_index >= len(offset_mapping)
                        or end_index >= len(offset_mapping)
                        or offset_mapping[start_index] is None
                        or offset_mapping[end_index] is None
                    ):
                        continue
                    # Don't consider answers with a length that is either < 0 or > max_answer_length.
                    if end_index < start_index or end_index - start_index + 1 > max_answer_length:
                        continue

                    try:
                        start_char = offset_mapping[start_index][0]
                        end_char = offset_mapping[end_index][1]
                        valid_answers.append(
                            {
                                "score": start_logits[start_index] + end_logits[end_index],
                                "text": context[start_char: end_char],
                                "answer_start" : start_char
                            }
                        )
                    except IndexError:
                        continue

        
        if len(valid_answers) > 0:
            best_answer = sorted(valid_answers, key=lambda x: x["score"], reverse=True)[0]
        else:
            # In the very rare edge case we have not a single non-null prediction, we create a fake prediction to avoid failure.
            best_answer = {"text": "", "score": 0.0}

        predictions[example["id"]] = {}
        predictions[example["id"]]["answer_start"] = best_answer["answer_start"]
        predictions[example["id"]]["text"] = best_answer["text"]

    return predictions

if TRAIN:
    for t in tqdm(range(0,num_of_runs)):
        annotation_datasets = unlabelled_datasets["train"]
        validation_features = annotation_datasets.map(
            prepare_validation_features,
            batched=True,
            remove_columns=annotation_datasets.column_names
        )
        raw_predictions = trainer.predict(validation_features)
        validation_features.set_format(type=validation_features.format["type"], columns=list(validation_features.features.keys()))

        final_predictions = postprocess_qa_predictions(annotation_datasets, validation_features, raw_predictions.predictions)
        new_formatted_predictions = {}
        for k, v in final_predictions.items():
            new_formatted_predictions[k] = v

        for i in range(len(unlabelled_datasets["train"])):
            unlabelled_datasets["train"][i]["answers"]["text"] = new_formatted_predictions[unlabelled_datasets["train"][i]["id"]]["text"]
            unlabelled_datasets["train"][i]["answers"]["answer_start"] = new_formatted_predictions[unlabelled_datasets["train"][i]["id"]]["answer_start"]

        # merge
        MERGED = concatenate_datasets([labelled_datasets["train"], unlabelled_datasets["train"]])
        merged_datasets = DatasetDict({"train":MERGED, "validation":original_datasets["validation"]})

        tokenizer = AutoTokenizer.from_pretrained(model_checkpoint)
        tokenized_datasets = merged_datasets.map(prepare_train_features, batched=True, remove_columns=merged_datasets["train"].column_names)
        model = AutoModelForQuestionAnswering.from_pretrained(model_checkpoint)
        model_name = model_checkpoint.split("/")[-1]
        args = TrainingArguments(
            f"{model_name}-finetuned-tydiqa",
            evaluation_strategy = "epoch",
            learning_rate=2e-5,
            per_device_train_batch_size=batch_size,
            per_device_eval_batch_size=batch_size,
            num_train_epochs=3,
            weight_decay=0.01,
            save_steps=20000
        )
        data_collator = default_data_collator
        trainer = Trainer(
            model,
            args,
            train_dataset=tokenized_datasets["train"],
            eval_dataset=tokenized_datasets["validation"],
            data_collator=data_collator,
            tokenizer=tokenizer,
        )
        trainer.train()
        trainer.save_model("f1")

# extracting bengali, and telugu from datasets
test_datasets = datasets.filter(lambda example: example["id"].startswith(('bengali', 'telugu')))["validation"]

# test_datasets

validation_features = test_datasets.map(
    prepare_validation_features,
    batched=True,
    remove_columns=test_datasets.column_names
)

# validation_features

raw_predictions = trainer.predict(validation_features)

# raw_predictions.predictions[0].shape

validation_features.set_format(type=validation_features.format["type"], columns=list(validation_features.features.keys()))

final_predictions = postprocess_qa_predictions(test_datasets, validation_features, raw_predictions.predictions)

metric = load_metric("squad") # Note: the metrics for QA tasks are all same so we can use squad also

formatted_predictions = [{"id": k, "prediction_text": v["text"]} for k, v in final_predictions.items()]
references = [{"id": ex["id"], "answers": ex["answers"]} for ex in test_datasets]
print(metric.compute(predictions=formatted_predictions, references=references))

# new_formatted_predictions = {}
# for k, v in final_predictions.items():
#     new_formatted_predictions[k] = v
# for ex in references:
#     if ex["answers"]["text"][0] != new_formatted_predictions[ex["id"]]["text"] and "హెక్టార్ల" not in ex["answers"]["text"][0]:
#         print("ACTUAL ANSWER: " + ex["answers"]["text"][0] + "    " + "PREDICTED ANSWER: " + new_formatted_predictions[ex["id"]]["text"])

# trainer.push_to_hub()

# !zip -r /content/test-tydiqa-trained.zip /content/test-tydiqa-trained
# from google.colab import files
# files.download("/content/test-tydiqa-trained.zip")
