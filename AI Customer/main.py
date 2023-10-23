from llama_cpp import Llama
import os
import json
import quixstreams as qx
import pandas as pd
from datetime import datetime
from huggingface_hub import hf_hub_download

REPO_ID = "TheBloke/Llama-2-7b-Chat-GGUF"
FILENAME = "llama-2-7b-chat.Q4_K_M.gguf"

hf_hub_download(repo_id=REPO_ID, filename=FILENAME, local_dir="model")

llm = Llama(model_path="./model/llama-2-7b-chat.Q4_K_M.gguf")
topic = os.environ["output"]
client = qx.QuixStreamingClient()

# Open a topic to publish data to
topic_producer = client.get_topic_producer(topic)
topic_consumer = client.get_topic_consumer(topic)

product = os.environ["product"]
scenario = f"The following transcript represents a converstation between you, a customer of a large electronics retailer called 'ACME electronics', and a support agent who you are contacting to resolve an issue with a defective {product} you purchased. Your goal is try and understand what your options are for resolving the issue. Please continue the conversation, but only reply as CUSTOMER:"

convostore = "conversation.json"

if os.path.exists(convostore):
    os.remove(convostore)
    print(f"The file {convostore} has been deleted.")
else:
    print(f"The file {convostore} does not exist yet.")

def generate_response(prompt, max_tokens=250, temperature=0.7, top_p=0.95, repeat_penalty=1.2, top_k=150):
    response = llm(
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stop=["AGENT:","CUSTOMER:","\n"],
        repeat_penalty=repeat_penalty,
        top_k=top_k,
        echo=True
    )

    return response["choices"][0]["text"]

def update_conversation(text, role, conversation_id, filename="conversation.json"):
    """
    Update the conversation history stored in a JSON file.

    Parameters:
        prompt (str): The prompt for the AI model, including the conversation history.
        role (str): The role of the agent (e.g., "customer" or "support_agent").
        conversation_id (str): The ID of the conversation.
        filename (str): The name of the file where the conversation history is stored.

    Returns:
        str: The generated reply.
    """
    # Read the existing conversation history from the file
    try:
        with open(filename, 'r') as file:
            conversation_history = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        # If the file does not exist or is empty, initialize an empty list
        conversation_history = []

    # Include the conversation history as part of the prompt
    full_history = "\n".join([f"{msg['role'].upper()}: {msg['text']}" for msg in conversation_history])
    prompt = scenario + '\n\n' + full_history + f'\nAGENT:{text}' + '\nCUSTOMER:'

    # Generate the reply using the AI model
    print("Thinking about my response....")
    reply = generate_response(prompt)  # This function should be defined elsewhere to handle the interaction with the AI model
    finalreply = reply.replace(prompt, ' ').replace('{', '').replace('}', '').replace('"', '').strip()
    print(f"My reply was '{finalreply}'")
    # Create a dictionary for the reply
    reply_dict = {
        "role": role.upper(),
        "conversation_id": conversation_id,
        "text": finalreply,
    }

    # Append the reply dictionary to the conversation history
    conversation_history.append(reply_dict)

    # Write the updated conversation history back to the file
    with open(filename, 'w') as file:
        json.dump(conversation_history, file)

    # Return the generated reply
    return finalreply

def publish_rp(response):
    print("Getting or creating stream...")
    stream = topic_producer.get_or_create_stream("conversation_001")
    stream.properties.name = "Chat conversation"

    chatmessage = {"timestamp": [datetime.utcnow()], "role": ["customer"], "text": [response], "conversation_id": ["001"]}
    df = pd.DataFrame(chatmessage)

    print("Publising stream...")
    stream.timeseries.buffer.publish(df)
    print("Published")

print("Listening for messages...")
counter = 0

# Callback triggered for each new data frame
def on_dataframe_received_handler(stream_consumer: qx.StreamConsumer, df: pd.DataFrame):
    chatmessage = df["text"][0]
    chatrole = df["role"][0]
    # Only respond if the message is from the opposite role
    if chatrole == "customer":
        print("(Detected one of my own messages)")
    elif chatrole == "agent":
        print(f"\n------\nRESPONDING T0: {chatmessage} \n------\n")
        custreply = update_conversation({chatmessage}, "customer", stream_consumer.stream_id, convostore)
        publish_rp(custreply)
        print("I have sent my reply to the agent.")
def on_stream_received_handler(stream_consumer: qx.StreamConsumer):
    stream_consumer.timeseries.on_dataframe_received = on_dataframe_received_handler

# subscribe to new streams being received
topic_consumer.on_stream_received = on_stream_received_handler

print("Listening to streams. Press CTRL-C to exit.")

# Handle termination signals and provide a graceful exit
qx.App.run()