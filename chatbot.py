import json
import os
import re
import logging
import hmac
import hashlib
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

# Slack signing secret for verification
slack_signing_secret = os.environ['SLACK_SIGNING_SECRET']


def verify_slack_request(slack_signature, timestamp, body):
    """
    Verify the request signature to authenticate Slack requests.
    """
    sig_basestring = f"v0:{timestamp}:{body}"
    my_signature = 'v0=' + hmac.new(
        bytes(slack_signing_secret, 'utf-8'),
        bytes(sig_basestring, 'utf-8'),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(my_signature, slack_signature)


def parse_slash_command(text):
    """
    Parse the slash command text for error details.
    """
    match = re.search(r"flow: (\w+) order id: (\d+) error: (.+)", text)
    if match:
        return match.groups()
    return None, None, None


def lambda_handler(event, context):
    try:
        logging.info("Received event: %s", event)

        # Extract necessary details from the event
        slack_event = json.loads(event['body'])
        timestamp = event['headers'].get('X-Slack-Request-Timestamp')
        slack_signature = event['headers'].get('X-Slack-Signature')

        logging.info("Verifying Slack request...")
        if not verify_slack_request(slack_signature, timestamp, event['body']):
            logging.warning("Verification failed")
            return {"statusCode": 403, "body": "Verification failed"}

        if "challenge" in slack_event:
            logging.info("Responding to Slack URL Verification Challenge")
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"challenge": slack_event["challenge"]})
            }

        if 'command' in slack_event['command'] == '/logerror':
            logging.info("Processing /logerror command")
            flow, order_id, error = parse_slash_command(slack_event['text'])

            if not (order_id and flow and error):
                logging.warning("Invalid format for /logerror command")
                raise ValueError(
                    "Invalid format. Please use 'flow: [flow] order id: [order_id] error: [error]'.")

            logging.info("Preparing data for DynamoDB")
            data = {
                "Order_id": order_id,
                "Flow": flow,
                "Error": error,
                "Timestamp": datetime.now().isoformat()
            }

            logging.info("Inserting data into DynamoDB")
            table.put_item(Item=data)

            logging.info("Sending confirmation message to Slack")
            response_message = f"Your issue with Order ID {order_id} has been logged."
            client.chat_postMessage(
                channel=slack_event['channel_id'], text=response_message)

            return {"statusCode": 200, "body": "Command processed"}

        logging.info("No action taken for the received event")
        return {"statusCode": 200, "body": "No action taken"}

    except SlackApiError as e:
        logging.error(f"Slack API Error: {e}")
        return {"statusCode": 200, "body": json.dumps({"Slack API Error": str(e)})}

    except Exception as e:
        logging.error(f"General Error: {e}")
        return {"statusCode": 500, "body": json.dumps({"Error": str(e)})}
