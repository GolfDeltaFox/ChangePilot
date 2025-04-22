# ChangePilot
A Pilot for ChangeDetection.io

ChangePilot leverages the notification system of ChangeDetection to detect broken watches (due to change in the DOM), analyse them and fix them autofatically.

ChangePilot tries to find the stock info of the main product in a page (even with multiple products or ads) by leveraging LLMs.

## Usage 

Add the following Notification to your general settings:

`post://<ChangePilot_server>:8000/repair?watch_url={{watch_url}}`


Example to run locally:

    sudo docker run -ti -v `pwd`/../models/:/models -e LLM_MODEL_PATH=/models/Ministral-8B-Instruct-2410-Q6_K.gguf -e API_KEY=<your_key> -e BASE_URL=http://<changedetection_server>:5003/api/v1 -v /mnt/changedetection/datastore:/datastore -e PORT=8000 -p 8000:8000 -ti changepilot
