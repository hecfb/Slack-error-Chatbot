import json
import os
import re
import logging
import boto3
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime

# Initialize logging
logging.basicConfig(level=logging.INFO)

# Initialize a DynamoDB client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE'])

# Initialize a Slack client
client = WebClient(token=os.environ['SLACK_BOT_TOKEN'])


def parse_message(text):
    """
    Process the text to extract flow, order_id, and error information using regular expressions.

    :param text: str
    :return: tuple
    """
    flow_match = re.search(r"flow: (\w+)", text)
    order_id_match = re.search(r"order id: (\d+)", text)
    error_match = re.search(r"error: (.+)", text)

    flow = flow_match.group(1) if flow_match else None
    order_id = order_id_match.group(1) if order_id_match else None
    error = error_match.group(1) if error_match else None

    return flow, order_id, error


def lambda_handler(event, context):
    try:
        slack_event = json.loads(event['body'])

        # Respond to Slack URL Verification Challenge
        if "challenge" in slack_event:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"challenge": slack_event["challenge"]})
            }

        text = slack_event['event']['text']
        flow, order_id, error = parse_message(text)

        if not (flow and order_id and error):
            raise ValueError("Could not extract all details from the message.")

        # Prepare the data as a JSON object
        data = {
            "Order_id": order_id,
            "Flow": flow,
            "Error": error,
            "Timestamp": datetime.now().isoformat()
        }

        # Insert into DynamoDB
        table.put_item(Item=data)

        # Respond to the user in Slack
        channel_id = slack_event['event']['channel']
        user = slack_event['event']['user']
        client.chat_postMessage(
            channel='channel',
            text=f"Hello <@{user}>, your issue with Order ID {order_id} has been logged."
        )

    except SlackApiError as e:
        logging.error(f"Slack API Error: {e}")
        return {"statusCode": 200, "body": json.dumps({"Slack API Error": str(e)})}

    except json.JSONDecodeError as e:
        logging.error(f"JSON Decode Error: {e}")
        return {"statusCode": 400, "body": json.dumps({"JSON Decode Error": str(e)})}

    except Exception as e:
        logging.error(f"General Error: {e}")
        return {"statusCode": 500, "body": json.dumps({"General Error": str(e)})}

    return {"statusCode": 200, "body": "Event received"}
