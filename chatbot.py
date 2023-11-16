import json
import os
import re
import logging
import hmac
import hashlib
import boto3
import urllib
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from datetime import datetime

# Initialize requirements
logging.basicConfig(level=logging.INFO)
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
    # Use the original URL-encoded body for signature verification
    sig_basestring = f"v0:{timestamp}:{body}"
    my_signature = 'v0=' + hmac.new(
        bytes(slack_signing_secret, 'utf-8'),
        bytes(sig_basestring, 'utf-8'),
        hashlib.sha256
    ).hexdigest()

    logging.info(f"Received Slack Signature: {slack_signature}")
    logging.info(f"Computed Signature: {my_signature}")

    return hmac.compare_digest(my_signature, slack_signature)


def parse_slash_command(text):
    """
    Parse the slash command text to extract order_id, flow, and error.
    """
    order_id_match = re.search(
        r"order[_\s]*id[=:\s]+\s*(\d+)", text, re.IGNORECASE)
    flow_match = re.search(
        r"flow[=:\s]+\s*{?\s*([^}]*)\s*}?", text, re.IGNORECASE)
    error_match = re.search(
        r"error[=:\s]+\s*([^\n,]+)", text, re.IGNORECASE)

    if order_id_match and flow_match and error_match:
        flow_list = [event.strip() for event in flow_match.group(1).split(',')]
        return {
            "order_id": int(order_id_match.group(1)),
            "flow": flow_list,
            "error": error_match.group(1).strip(),
            "original_input": text
        }


def lambda_handler(event, context):
    print(event)
    try:
        logging.info("Received event: %s", event)

        # Extract necessary details from the event
        parsed_body = urllib.parse.parse_qs(event['body'])
        slack_event = {k: v[0] for k, v in parsed_body.items()}

        # Now use 'slack_event' as a dictionary with the parsed parameters
        timestamp = event['headers'].get('X-Slack-Request-Timestamp')
        slack_signature = event['headers'].get('X-Slack-Signature')

        if not verify_slack_request(slack_signature, timestamp, event['body']):
            return {
                "statusCode": 200,  # Always return 200 OK to acknowledge receipt
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "response_type": "ephemeral",
                    "text": "Verification failed"
                })
            }

        if 'command' in slack_event and slack_event['command'] == '/logerror':
            parsed_data = parse_slash_command(slack_event['text'])

            if not parsed_data:
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({
                        "response_type": "ephemeral",
                        "text": "Invalid format. Please use 'order_id: [order_id] flow: [flow] error: [error]'."
                    })
                }
            else:
                order_id = parsed_data["order_id"]
                flow = parsed_data["flow"]
                error = parsed_data["error"]

            data = {
                "order_id": order_id,
                "Flow": flow,
                "Error": error,
                "Timestamp": datetime.now().isoformat()
            }

            table.put_item(Item=data)

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "response_type": "in_channel",
                    "text": f"Your issue with Order ID {order_id} has been logged."
                })
            }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "response_type": "ephemeral",
                "text": "No action taken"
            })
        }

    except SlackApiError as e:
        logging.error(f"Slack API Error: {e}")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "response_type": "ephemeral",
                "text": f"Slack API Error: {str(e)}"
            })
        }

    except Exception as e:
        logging.error(f"General Error: {e}")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "response_type": "ephemeral",
                "text": f"Error: {str(e)}"
            })
        }
