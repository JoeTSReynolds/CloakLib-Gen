# Cloaked Dataset & Demo

This repository contains a dataset generator, an S3 bucket uploader, and a demo web application for experimenting with **image cloaking** using [Fawkes](https://sandlab.cs.uchicago.edu/fawkes/). It provides tools for generating and managing cloaked datasets locally and on AWS, and includes a frontend + backend demo for testing cloaking against different facial recognition models.

---

## Repository Contents

* **Dataset Generator (`dataset_generator.py`)**

  * Create and manage a dataset of cloaked images/videos.
  * Supports **local processing** and **AWS S3/EC2 Spot Instance processing**.
  * Allows classification of images with attributes like age, gender, race, expression, and more.

* **Bucket Uploader (`bucket_uploader.py`)**

  * Upload, reset, rebalance, and maintain S3-hosted datasets.
  * Supports dataset health checks and duplicate removal.

* **Demo Web Application**

  * **Backend (Python + Node.js)**

    * Python backend for cloaking operations.
    * Node.js backend for Human AI facial recognition.
  * **Frontend (React Native + Expo)**

    * Upload and cloak images.
    * Compare results against **AWS Rekognition** and **Human AI**.
    * Includes batch testing mode for evaluation.

* **Helper Scripts**

  * `spot_instance_setup.sh` → bootstrap script for AWS Spot Instances.

---

## Setup

### Dataset Generator Prerequisites

Requires **Python 3.8 or older** with:

```
fawkes==1.0.4
mtcnn==0.1.1
tqdm==4.67.1
opencv-python==4.12.0.88
boto3==1.37.38
torch==2.4.1   # optional, enables GPU acceleration if CUDA available
```

> 💡 Without Torch, only CPU is used. With Torch + CUDA, GPU acceleration is enabled.
> Approx. storage needs: \~10GB without Torch, \~20GB with Torch + CUDA drivers.

Install dependencies:

```bash
pip install mtcnn==0.1.1 fawkes tqdm opencv-python boto3 awscli torch
```

Remove `torch` if limited by space.

---

### Dataset Generator AWS Setup

1. Create an AWS S3 bucket.
2. Initialize folder structure:

```bash
python dataset_generator.py --aws-init --aws-bucket YOUR_BUCKET_NAME --aws-region BUCKET_REGION
```

3. Use the provided `spot_instance_setup.sh` to set up AWS EC2 Spot Instances. Update placeholders with your:

   * `AWS_ACCESS_KEY_ID`
   * `AWS_SECRET_ACCESS_KEY`
   * `BUCKET_NAME`
   * `BUCKET_REGION`

Logs from instance setup: `/var/log/user-data.log`

---

### Demo Python Backend

Requires **Python 3.8 or older** with:

```
fawkes==1.0.4
mtcnn==0.1.1
boto3==1.37.38
botocore==1.37.38
Flask==3.1.2
Flask_Cors==5.0.0
opencv_python==4.12.0.88
regex==2024.11.6
requests==2.32.5
```

---

### Demo Node Backend

Requires **Node.js (v22.9.0)** and **npm (11.4.2)**.
Dependencies inside `backend/human`:

```
@tensorflow/tfjs-node ^4.22.0
@vladmandic/human ^3.3.5
express ^5.1.0
multer ^2.0.2
sharp ^0.33.4
```

---

### Demo Frontend

Inside the `frontend` folder, install with npm. Key dependencies include:

```
expo ^49.0.0
react 18.2.0
react-native 0.72.10
nativewind ^4.1.23
@react-navigation/native ^6.1.9
@expo/webpack-config ^19.0.0
```

(See full dependency list in the docs above.)

---

## How to Run

### Dataset Generator

View help:

```bash
python dataset_generator.py -h
```

**Examples:**

* Cloak a single image:

```bash
python dataset_generator.py --cloak --mode high --name "Alice" --age Adult --gender F ./images/alice.jpg
```

* Cloak all images in a folder with 8 threads:

```bash
python dataset_generator.py --cloak --dir ./photos --threads 8 --batch-size 16
```

* Initialize S3 bucket structure:

```bash
python dataset_generator.py --aws-init --aws-bucket my-dataset-bucket --aws-region eu-west-2
```

* Run cloaking on AWS with all levels:

```bash
python dataset_generator.py --aws-spot --aws-bucket my-dataset-bucket --aws-region eu-west-2 --all-levels
```

---

### Bucket Uploader

View help:

```bash
python bucket_uploader.py -h
```

**Examples:**

* Upload data with CSV metadata + local files:

```bash
python bucket_uploader.py --bucket-name my-dataset-bucket --csv dataset.csv --data ./local_data
```

* Reset all dataset files in S3:

```bash
python bucket_uploader.py --bucket-name my-dataset-bucket --reset
```

* Reset only cloaked files at `high` level:

```bash
python bucket_uploader.py --bucket-name my-dataset-bucket --reset-level high
```

* Rebalance dataset with stricter tolerance:

```bash
python bucket_uploader.py --bucket-name my-dataset-bucket --rebalance --tolerance 0.05
```

* Run dataset health check:

```bash
python bucket_uploader.py --bucket-name my-dataset-bucket --health
```

---

## Demo

The demo web app lets you:

* Upload & cloak images.
* Compare cloaked/uncloaked recognition results against **AWS Rekognition** and **Human AI**.
* Run batch tests and export CSV results.