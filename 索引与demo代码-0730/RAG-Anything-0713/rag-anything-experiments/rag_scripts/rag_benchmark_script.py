import os
import re
import math
import json
import argparse
#import fitz
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
from tqdm import tqdm
import requests
from eval.eval_score import eval_score, eval_acc_and_f1, show_results
#from eval.extract_answer import extract_answer

model = "gemma3"

def send_request_to_rag(q):
    query = {"question" : q}
    answer = requests.post("http://localhost:8080/query", json=query)
    print(f" send request to rag answer: {answer.json()}")
    return answer.json()["answer"]

def extract_answer_ollama(question, response, prompt):
    msg = [
            {
                "role": "user",
                "content": prompt,
            },
            {
                "role": "assistant",
                "content": "\n\nQuestion:{}\nAnalysis:{}\n".format(question, response)
            }
          ]
    data = {"model": model, "messages": msg, "temperature":0.0, "max_tokens":256,"top_p":1,"frequency_penalty":0,"presence_penalty":0}
    answer = requests.post("http://172.17.0.3:11434/v1/chat/completions", json=data)
    js_answer = answer.json()
    print(js_answer)
    return js_answer["choices"][0]["message"]["content"]
    

def load_questions(args):
    print(args.output_path)
    if os.path.exists(args.output_path):
        with open(args.output_path) as f:
            samples = json.load(f)
    else:
        with open(args.input_path, 'r') as f:
            samples = json.load(f)
    # load evaluation prompt
    with open("./eval/prompt_for_answer_extraction.md") as f:
        prompt = f.read()


    for sample in tqdm(samples):
        if "score" in sample:
            score = sample["score"]
        else:
            #response = get_response_concat(model, sample["question"], concat_image_list, max_new_tokens=args.max_tokens, temperature=args.temperature)
            response = send_request_to_rag(sample["question"])
            if response == 'Failed':
                tmp_concat_num = args.concat_num - 1
                while response == 'Failed' and tmp_concat_num > 0:
                    concat_image_list = concat_images(image_list, concat_num=tmp_concat_num)
                    response = get_response_concat(model, sample["question"], concat_image_list, max_new_tokens=args.max_tokens, temperature=args.temperature)
                    tmp_concat_num -= 1

            sample["response"] = response
            extracted_res = extract_answer_ollama(sample["question"], response, prompt)
            sample["extracted_res"] = extracted_res
            try:
                pred_ans = extracted_res.split("Answer format:")[0].split("Extracted answer:")[1].strip()
                score = eval_score(sample["answer"], pred_ans, sample["answer_format"])
            except:
                pred_ans = "Failed to extract"
                score = 0.0
            sample["pred"] = pred_ans
            sample["score"] = score

        acc, f1 = eval_acc_and_f1(samples)
        print("--------------------------------------")
        print("Question: {}".format(sample["question"]))
        print("Response: {}".format(sample["response"]))
        print("Gt: {}\tPred: {}\tScore: {}".format(sample["answer"], sample["pred"], sample["score"]))
        print("Avg acc: {}".format(acc))
        print("Avg f1: {}".format(f1))
        
        with open(args.output_path, 'w') as f:
            json.dump(samples, f)
    
    show_results(samples, show_path=re.sub("\.json$", ".txt", args.output_path))


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_path", type=str, default="./data/samples.json")
    parser.add_argument("--document_path", type=str, default="./data/documents")
    parser.add_argument("--extractor_prompt_path", type=str, default="./eval/prompt_for_answer_extraction.md")
    parser.add_argument("--model_name", type=str, default="internvl", choices=["internvl", "4khd", "minicpm_llama3"])
    parser.add_argument("--model_cached_path", type=str, default=None)
    parser.add_argument("--max_pages", type=int, default=120)
    parser.add_argument("--resolution", type=int, default=144)
    parser.add_argument("--max_tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()
    
    args.output_path = f'./results/res_ollama.json'
    load_questions(args)