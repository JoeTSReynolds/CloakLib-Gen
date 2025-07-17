# CloakLib-Gen
Generator for a library of cloaked and non cloaked images and videos

## Dependencies
Only works with python 3.8.x so make sure you are using 3.8 (e.g. 3.8.10). This is due to fawkes dependencies

Libraries:
`pip install fawkes`
`pip install tqdm`

## Usage

`python image_lib_gen.py [-h] [--batch-size BATCH_SIZE] [--threads THREADS] [--mode {low,mid,high}] input_dir `

This will process images and videos in the input directory and add them to the (local) library in appropriate places. Does not delete the originals from the input folder.



# Fawkes and Rekognition demo

Go into frontend and type `npm install`


Start the backend server (just have it run in a separate terminal)

In frontend, type `npx expo start --web`