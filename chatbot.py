import json
import os
import re
import boto3
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import spacy
import zipfile
import sys

# Initialize a S3 client
s3_client = boto3.client('s3')

# Initialize a DynamoDB client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

# Initialize a Slack client
client = WebClient(token=os.environ['SLACK_BOT_TOKEN'])


def parse_message(text, nlp):
    """
    Process the text with Spacy NLP to extract flow, order_id, and error information.

    :param text: str
    :param nlp: Spacy Language model
    :return: tuple
    """
    doc = nlp(text)

    flow = None
    order_id = None
    error = None

    # Look for entities and match with corresponding details
    for ent in doc.ents:
        if ent.label_ == "NOUN":
            lower_text = ent.text.lower()
            if "flow" in lower_text:
                flow = ent.text.split()[-1]
            elif "order id" in lower_text:
                order_id = ent.text.split()[-1]
            elif "error" in lower_text:
                error = ent.text.split()[-1]

    # Fallback to regex if NLP parsing didn't work
    if not flow or not order_id or not error:
        flow_match = re.search(r"flow: (\w+)", text)
        order_id_match = re.search(r"order id: (\d+)", text)
        error_match = re.search(r"error: (.+)", text)

        flow = flow or (flow_match.group(1) if flow_match else None)
        order_id = order_id or (order_id_match.group(1)
                                if order_id_match else None)
        error = error or (error_match.group(1) if error_match else None)

    return flow, order_id, error


def lambda_handler(event, context):
    # Define S3 bucket and object key
    bucket_name = os.environ['S3_BUCKET']
    zip_key = 'dependencies.zip'

    # Define the download path and extraction directory
    extract_path = '/tmp/extracted/'
    if not os.path.exists(extract_path):
        download_path = '/tmp/dependencies.zip'

        try:
            # Download the zip file from S3
            s3_client.download_file(bucket_name, zip_key, download_path)
        except boto3.exceptions.S3DownloadError as e:
            log_data = {"error": f"S3 Download Error: {str(e)}"}
            print(json.dumps(log_data))
            return {"statusCode": 500, "body": json.dumps(log_data)}

        try:
            # Extract the zip file
            with zipfile.ZipFile(download_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
        except zipfile.BadZipFile as e:
            log_data = {"error": f"Zip Extraction Error: {str(e)}"}
            print(json.dumps(log_data))
            return {"statusCode": 500, "body": json.dumps(log_data)}

    # Add the extracted directory to sys.path
    sys.path.append(extract_path)

    # Load Spacy NLP model
    nlp = spacy.load("en_core_web_sm")

    try:
        slack_event = json.loads(event['body'])

        if "challenge" in slack_event:
            return {"statusCode": 200, "body": json.dumps({"challenge": slack_event["challenge"]})}

        text = slack_event['event']['text']
        flow, order_id, error = parse_message(text, nlp)

        if not (flow and order_id and error):
            raise ValueError("Could not extract all details from the message.")

        try:
            # Prepare the data as a JSON object
            data = {
                "Order_id": order_id,
                "Flow": flow,
                "Error": error
            }

            # Insert into DynamoDB
            table.put_item(Item={'order_id': order_id,
                           'data': json.dumps(data)})
        except boto3.exceptions.Boto3Error as e:
            log_data = {"DynamoDB Error": str(
                e), "Order_id": order_id, "Flow": flow, "Error": error}
            print(json.dumps(log_data))
            return {"statusCode": 500, "body": json.dumps(log_data)}

        # Respond to the user in Slack
        channel_id = slack_event['event']['channel']
        user = slack_event['event']['user']
        client.chat_postMessage(
            channel=channel_id,
            text=f"Hello <@{user}>, your issue with Order ID {order_id} has been logged."
        )

    except SlackApiError as e:
        log_data = {"Slack API Error": str(e)}
        print(json.dumps(log_data))
        return {"statusCode": 200, "body": json.dumps(log_data)}

    except json.JSONDecodeError as e:
        log_data = {"JSON Decode Error": str(e)}
        print(json.dumps(log_data))
        return {"statusCode": 400, "body": json.dumps(log_data)}

    except Exception as e:
        log_data = {"General Error": str(e)}
        print(json.dumps(log_data))
        return {"statusCode": 500, "body": json.dumps(log_data)}

    return {"statusCode": 200, "body": "Event received"}
