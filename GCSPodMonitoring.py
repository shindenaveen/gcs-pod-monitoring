import subprocess
import time
import logging
from datetime import datetime
import os
import requests

# Logging setup
log_filename = f"/path/to/your/dir/Logs/gcstoolsMonitoring_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
logging.basicConfig(filename=log_filename, level=logging.INFO, format='%(asctime)s - %(message)s')

# Email settings
EMAIL_SENDER = "you@example.com"
EMAIL_RECEIVER = "recipient@example.com"

def set_env(kubeconfigfile):
    os.environ['KUBECONFIG'] = kubeconfigfile
    logging.info(f"Environment variable KUBECONFIG set to: {kubeconfigfile}")

def get_all_pods(namespace, kubeconfigfile):
    command = f"kubectl get pods -n {namespace} --kubeconfig {kubeconfigfile} --no-headers"
    try:
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, check=True)
        return result.stdout.splitlines()
    except subprocess.CalledProcessError as e:
        logging.error(f"Error executing command: {command}")
        logging.error(f"Return code: {e.returncode}")
        logging.error(f"Stderr: {e.stderr}")
        raise

def delete_pod(pod_name, namespace):
    command = f"kubectl delete pod {pod_name} -n {namespace}"
    subprocess.run(command, shell=True, check=True)
    logging.info(f"Deleted pod {pod_name} in namespace {namespace}.")

def restart_pod(pod_name, namespace):
    command = f"kubectl rollout restart deployment {pod_name} -n {namespace}"
    subprocess.run(command, shell=True, check=True)
    logging.info(f"Restarted pod {pod_name} in namespace {namespace}.")

def check_url_status(url_dict, status_report_urls):
    for name, url in url_dict.items():
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            logging.info(f"URL {url} ({name}) is UP.")
            status_report_urls.append({"name": name, "url": url, "status": "UP"})
        except requests.exceptions.RequestException as e:
            logging.error(f"Error accessing URL {url} ({name}): {str(e)}")
            status_report_urls.append({"name": name, "url": url, "status": "DOWN"})

def send_email_table(pod_status_list, url_status_list, env):
    if not any(entry['status'] not in {"Running", "UP", "Skipped (Exception List)"} for entry in pod_status_list + url_status_list):
        return

    status_colors = {
        "Running": "green", "Not Running": "red", "Missing": "orange",
        "Recovered": "blue", "Manual Intervention Needed": "purple",
        "Pod Restarted": "blue", "Pod Deleted": "red",
        "Manual Restart Needed": "brown", "Scheduled Maintenance": "yellow",
        "UP": "green", "DOWN": "red"
    }

    html_content = """<html><body>
<h3>Kubernetes Pod Status Alert</h3>
<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">
<tr><th>Namespace</th><th>Pod Name</th><th>Status</th><th>Action Taken</th></tr>"""

    for entry in pod_status_list:
        color = status_colors.get(entry['status'], "black")
        html_content += f"<tr><td>{entry['namespace']}</td><td>{entry['pod_name']}</td><td style='color:{color};'>{entry['status']}</td><td>{entry['action']}</td></tr>"

    html_content += "</table>"

    if url_status_list:
        html_content += """<br><br><h3>Service URL Status</h3>
<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">
<tr><th>URL Name</th><th>URL</th><th>Status</th></tr>"""
        for entry in url_status_list:
            color = status_colors.get(entry['status'].split()[0], "black")
            html_content += f"<tr><td>{entry['name']}</td><td>{entry['url']}</td><td style='color:{color};'>{entry['status']}</td></tr>"
        html_content += "</table>"

    html_content += "</body></html>"

    EMAIL_SUBJECT = f"GCS : {env} GCSTOOLS Monitoring Status Email"
    email_content = f"""From: {EMAIL_SENDER}
To: {EMAIL_RECEIVER}
Subject: {EMAIL_SUBJECT}
MIME-Version: 1.0
Content-Type: text/html

{html_content}
"""

    try:
        process = subprocess.Popen(["/usr/sbin/sendmail", "-t"], stdin=subprocess.PIPE)
        process.communicate(email_content.encode("utf-8"))
        logging.info("Email notification sent.")
    except Exception as e:
        logging.error(f"Error sending email: {e}")

def read_exception_file(filepath):
    excepted_pods = []
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                excepted_pods = [line.strip() for line in f if line.strip()]
            logging.info(f"Loaded {len(excepted_pods)} pod(s) from exception file.")
        except Exception as e:
            logging.error(f"Error reading exception file {filepath}: {e}")
    else:
        logging.info(f"Exception file {filepath} not found.")
    return excepted_pods

def check_pod_status(namespace, pod_list, status_report, kubeconfigfile):
    pod_status_lines = get_all_pods(namespace, kubeconfigfile)
    exception_file_path = "/path/to/your/dir/GCSToolsException_Monitoring.txt"
    excepted_pods = read_exception_file(exception_file_path)

    for pod_name in pod_list:
        if any(excepted in pod_name for excepted in excepted_pods):
            logging.info(f"Skipping pod {pod_name} as it's in exception list.")
            status_report.append({"namespace": namespace, "pod_name": pod_name, "status": "Skipped (Exception List)", "action": "None"})
            continue
        pod_found = False
        for line in pod_status_lines:
            if pod_name in line:
                pod_found = True
                full_pod_name = line.split()[0]
                pod_status = line.split()[2]
                if pod_status == "Running":
                    status_report.append({"namespace": namespace, "pod_name": full_pod_name, "status": "Running", "action": "None"})
                else:
                    delete_pod(full_pod_name, namespace)
                    status_report.append({"namespace": namespace, "pod_name": full_pod_name, "status": "Not Running", "action": "Pod Deleted"})
                    time.sleep(300)
                    check_pod_after_wait(full_pod_name, namespace, status_report)
        if not pod_found:
            restart_pod(pod_name, namespace)
            status_report.append({"namespace": namespace, "pod_name": pod_name, "status": "Missing", "action": "Pod Restarted"})

def check_pod_after_wait(pod_name, namespace, status_report):
    command = f"kubectl get pod {pod_name} -n {namespace}"
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    pod_status = result.stdout.strip()
    if pod_status:
        status = pod_status.split()[2]
        if status == "Running":
            status_report.append({"namespace": namespace, "pod_name": pod_name, "status": "Running", "action": "Recovered"})
        else:
            status_report.append({"namespace": namespace, "pod_name": pod_name, "status": "Not Running", "action": "Manual Intervention Needed"})
    else:
        status_report.append({"namespace": namespace, "pod_name": pod_name, "status": "Missing", "action": "Manual Restart Needed"})

def parse_input_file(input_file):
    pods = {"IAP": [], "OAPM": [], "DEVOPS": [], "JS7PRD": [], "JS7NPD": [], "URLS": {}}
    current_section = None
    with open(input_file, "r") as file:
        for line in file:
            line = line.strip()
            if line in ["[IAP]", "[OAPM]", "[DEVOPS]", "[JS7PRD]", "[JS7NPD]", "[URLS]"]:
                current_section = line.strip("[]")
            elif line and current_section:
                if current_section == "URLS" and "=" in line:
                    name, url = line.split("=", 1)
                    pods["URLS"][name.strip()] = url.strip()
                else:
                    pods[current_section].append(line)
    return pods

def determine_environment():
    hostname = os.uname().nodename
    if hostname[-1] == 'p':
        return {
            "kubeconfigfile": "/path/to/your/prod/kubeconfig",
            "iap_namespace": "iap-prd",
            "oapm_namespace": "oapm-prd",
            "devops_namespace": "devops-prd",
            "js7comm_namespace": "js7comm-prd",
            "env": "PRD"
        }
    elif hostname[-1] == 's':
        return {
            "kubeconfigfile": "/path/to/your/npd/kubeconfig",
            "iap_namespace": "iap-npd",
            "oapm_namespace": "oapm-npd",
            "devops_namespace": "devops-npd",
            "js7comm_namespace": "js7comm-npd",
            "env": "NPD"
        }
    else:
        raise ValueError("Unknown hostname pattern")

def main():
    input_file = "/path/to/your/dir/pods_input.txt"
    pod_dict = parse_input_file(input_file)
    env_config = determine_environment()
    set_env(env_config["kubeconfigfile"])
    status_report = []
    url_status_report = []

    if pod_dict["OAPM"]:
        check_pod_status(env_config["oapm_namespace"], pod_dict["OAPM"], status_report, env_config["kubeconfigfile"])
    if pod_dict["IAP"]:
        check_pod_status(env_config["iap_namespace"], pod_dict["IAP"], status_report, env_config["kubeconfigfile"])
    if pod_dict["DEVOPS"]:
        check_pod_status(env_config["devops_namespace"], pod_dict["DEVOPS"], status_report, env_config["kubeconfigfile"])
    if pod_dict["JS7PRD"]:
        check_pod_status("js7comm-prd", pod_dict["JS7PRD"], status_report, env_config["kubeconfigfile"])
    if pod_dict["JS7NPD"]:
        check_pod_status("js7comm-npd", pod_dict["JS7NPD"], status_report, env_config["kubeconfigfile"])
    if pod_dict["URLS"]:
        check_url_status(pod_dict["URLS"], url_status_report)

    if status_report or url_status_report:
        send_email_table(status_report, url_status_report, env_config["env"])

if __name__ == "__main__":
    main()
