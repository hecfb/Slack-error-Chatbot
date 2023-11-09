import json
import os
import re
import slack
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import spacy
import boto3

# Load Spacy NLP model
nlp = spacy.load("en_core_web_sm")

# Initialize a DynamoDB client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['YOUR_DYNAMODB_TABLE_NAME'])

# Initialize a Slack client
client = WebClient(token=os.environ['SLACK_BOT_TOKEN'])


def parse_message(text):
    """
    Process the text with Spacy NLP to extract flow, order_id, and error information.

    :param text: str
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
    """
    Handle incoming Slack events, validate them, and respond accordingly.

    :param event: dict
    :param context: LambdaContext
    :return: dict
    """
    slack_event = json.loads(event['body'])

    # Slack URL verification handshake
    if "challenge" in slack_event:
        return {"statusCode": 200, "body": json.dumps({"challenge": slack_event["challenge"]})}

    try:
        # Extract message details
        text = slack_event['event']['text']
        flow, order_id, error = parse_message(text)

        if not (flow and order_id and error):
            raise ValueError("Could not extract all details from the message.")

        # Insert into DynamoDB
        table.put_item(
            Item={
                'order_id': order_id,
                'flow': flow,
                'error': error,
            }
        )

        # Respond to the user in Slack
        channel_id = slack_event['event']['channel']
        user = slack_event['event']['user']
        client.chat_postMessage(
            channel=channel_id,
            text=f"Hello <@{user}>, your issue with Order ID {order_id} has been logged."
        )

    except SlackApiError as e:
        # Handle Slack API errors here
        print(f"Slack API Error: {e}")
        return {"statusCode": 200, "body": json.dumps({"error": str(e)})}

    except ValueError as e:
        # Handle extraction errors
        print(f"Value Error: {e}")
        return {"statusCode": 200, "body": json.dumps({"error": str(e)})}

    return {"statusCode": 200, "body": "Event received"}
