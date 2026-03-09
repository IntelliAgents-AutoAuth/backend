import json
import numpy as np
import os
import pickle
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import torch
from transformers import (
    BertTokenizer,
    BertForSequenceClassification,
    Trainer,
    TrainingArguments
)
from torch.utils.data import Dataset

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

BASE_DIR        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH       = os.path.join(BASE_DIR, "training-data", "policy_section_finder_training_data.json")
MODEL_SAVE_PATH = os.path.join(BASE_DIR, "agents", "section_finder_model")
MODEL_NAME      = "bert-base-uncased"
MAX_LENGTH      = 256
EPOCHS          = 10
BATCH_SIZE      = 4
LEARNING_RATE   = 2e-5

LABELS = {
    "NOT_REQUIRED_DOC_SECTION": 0,
    "REQUIRED_DOC_SECTION":     1
}
ID2LABEL = {0: "NOT_REQUIRED_DOC_SECTION", 1: "REQUIRED_DOC_SECTION"}

print("=" * 60)
print("  SECTION FINDER MODEL TRAINER")
print("=" * 60)


# ─────────────────────────────────────────────
# STEP 1 — Load training data
# ─────────────────────────────────────────────

print("\n📂 Loading training data...")

with open(DATA_PATH, "r") as f:
    raw_data = json.load(f)

texts  = [d["input"] for d in raw_data]
labels = [LABELS[d["label"]] for d in raw_data]

print(f"   Total samples    : {len(texts)}")
print(f"   Positive (REQUIRED)    : {sum(labels)}")
print(f"   Negative (NOT REQUIRED): {len(labels) - sum(labels)}")


# ─────────────────────────────────────────────
# STEP 2 — Split train / test
# ─────────────────────────────────────────────

train_texts, test_texts, train_labels, test_labels = train_test_split(
    texts, labels,
    test_size    = 0.2,
    random_state = 42,
    stratify     = labels
)

print(f"\n📊 Train/Test Split:")
print(f"   Train samples : {len(train_texts)}")
print(f"   Test samples  : {len(test_texts)}")


# ─────────────────────────────────────────────
# STEP 3 — Load tokenizer
# ─────────────────────────────────────────────

print(f"\n🔄 Loading tokenizer: {MODEL_NAME}")
tokenizer = BertTokenizer.from_pretrained(MODEL_NAME)
print("   ✅ Tokenizer loaded")


# ─────────────────────────────────────────────
# STEP 4 — Tokenize data
# ─────────────────────────────────────────────

print("\n🔄 Tokenizing data...")

train_encodings = tokenizer(
    train_texts,
    truncation = True,
    padding    = "max_length",
    max_length = MAX_LENGTH,
    return_tensors = "pt"
)

test_encodings = tokenizer(
    test_texts,
    truncation = True,
    padding    = "max_length",
    max_length = MAX_LENGTH,
    return_tensors = "pt"
)

print("   ✅ Tokenization complete")


# ─────────────────────────────────────────────
# STEP 5 — Create Dataset class
# ─────────────────────────────────────────────

class SectionDataset(Dataset):
    def __init__(self, encodings, labels):
        self.encodings = encodings
        self.labels    = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        item = {
            key: val[idx].clone().detach()
            for key, val in self.encodings.items()
        }
        item["labels"] = torch.tensor(self.labels[idx])
        return item


train_dataset = SectionDataset(train_encodings, train_labels)
test_dataset  = SectionDataset(test_encodings,  test_labels)

print(f"\n📦 Datasets created:")
print(f"   Train dataset : {len(train_dataset)} samples")
print(f"   Test dataset  : {len(test_dataset)} samples")


# ─────────────────────────────────────────────
# STEP 6 — Load BERT model
# ─────────────────────────────────────────────

print(f"\n🔄 Loading BERT model: {MODEL_NAME}")

model = BertForSequenceClassification.from_pretrained(
    MODEL_NAME,
    num_labels = 2,
    id2label   = ID2LABEL,
    label2id   = LABELS
)

print(f"   ✅ Model loaded")
print(f"   Parameters: {model.num_parameters():,}")


# ─────────────────────────────────────────────
# STEP 7 — Training arguments
# ─────────────────────────────────────────────

os.makedirs(MODEL_SAVE_PATH, exist_ok=True)
os.makedirs("./logs", exist_ok=True)

training_args = TrainingArguments(
    output_dir                  = MODEL_SAVE_PATH,
    num_train_epochs            = EPOCHS,
    per_device_train_batch_size = BATCH_SIZE,
    per_device_eval_batch_size  = BATCH_SIZE,
    warmup_steps                = 10,
    weight_decay                = 0.01,
    logging_dir                 = "./logs",
    logging_steps               = 5,
    eval_strategy               = "epoch",
    save_strategy               = "epoch",
    load_best_model_at_end      = True,
    metric_for_best_model       = "eval_loss",
    learning_rate               = LEARNING_RATE,
    use_cpu                     = not torch.cuda.is_available(),
)

print(f"\n⚙️  Training Configuration:")
print(f"   Epochs         : {EPOCHS}")
print(f"   Batch size     : {BATCH_SIZE}")
print(f"   Learning rate  : {LEARNING_RATE}")
print(f"   Max length     : {MAX_LENGTH}")
print(f"   Device         : {'GPU' if torch.cuda.is_available() else 'CPU'}")


# ─────────────────────────────────────────────
# STEP 8 — Train
# ─────────────────────────────────────────────

trainer = Trainer(
    model           = model,
    args            = training_args,
    train_dataset   = train_dataset,
    eval_dataset    = test_dataset,
)

print("\n🚀 Starting training...")
print("-" * 60)

trainer.train()

print("\n✅ Training complete!")


# ─────────────────────────────────────────────
# STEP 9 — Evaluate
# ─────────────────────────────────────────────

print("\n📊 Evaluating model...")

predictions = trainer.predict(test_dataset)
pred_labels = np.argmax(predictions.predictions, axis=1)

accuracy = accuracy_score(test_labels, pred_labels)

print("\n" + "=" * 60)
print("  EVALUATION RESULTS")
print("=" * 60)
print(f"\n  Accuracy: {round(accuracy * 100, 2)}%")
print("\n  Classification Report:")
print(classification_report(
    test_labels,
    pred_labels,
    target_names=["NOT_REQUIRED_DOC", "REQUIRED_DOC"]
))


# ─────────────────────────────────────────────
# STEP 10 — Save model and tokenizer
# ─────────────────────────────────────────────

print("\n💾 Saving model...")

model.save_pretrained(MODEL_SAVE_PATH)
tokenizer.save_pretrained(MODEL_SAVE_PATH)

# Save label mapping
with open(f"{MODEL_SAVE_PATH}/label_map.json", "w") as f:
    json.dump({
        "labels":   LABELS,
        "id2label": ID2LABEL
    }, f, indent=2)

print(f"   ✅ Model saved to: {MODEL_SAVE_PATH}/")
print(f"   ✅ Tokenizer saved")
print(f"   ✅ Label map saved")

print("\n" + "=" * 60)
print("  TRAINING COMPLETE")
print("=" * 60)
print(f"\n  Model location : {MODEL_SAVE_PATH}/")
print(f"  Final accuracy : {round(accuracy * 100, 2)}%")
print(f"\n  Next step:")
print(f"  Run: python test_section_finder.py")
print("=" * 60)