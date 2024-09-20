import urllib.request
import json
import subprocess
import re
import glob
import tempfile
import argparse
from halo import Halo
from colorama import init, Fore, Style

init(autoreset=True)

def get_creds():
    with open('cred.json') as f:
        cred = json.load(f)
        api_url = cred['PROMPT_FLOW_API_URL']
        api_key = cred['PROMPT_FLOW_API_KEY']
        return {'api_url': api_url, 'api_key': api_key}
    return RuntimeError("Credentials not found")

def parse_bicep(input_dir):
    input_dir = re.sub(r'\\', '/', input_dir) + "/"
    bicep_files = glob.glob(input_dir + '**/*.bicep', recursive=True)
    uniq_resource_types = set()
    resource_pattern = re.compile(r'^resource\s\w+[a-zA-Z0-9\./@\'].*\{')

    for ch_file in bicep_files:
        with open(ch_file, 'r') as f:
            for line in f.readlines():
                resource = resource_pattern.findall(line)
                if len(resource) > 0:
                    _, _, type_ = resource[0].split()[:3]
                    type_ = type_.split('\'')[1]
                    uniq_resource_types.add(type_.split('@')[0])
    return uniq_resource_types

def parse_output(output):
    roles_str = json.loads(output)['chat_output']
    roles_str = re.sub(r'```json', '', roles_str)
    roles_str = re.sub(r'```', '', roles_str)
    return json.loads(roles_str)


def get_gpt_roles(api_details, uniq_resource_types):
    types_str = ','.join(sorted(list(uniq_resource_types)))
    api_url = api_details['api_url']
    api_key = api_details['api_key']

    headers = {'Content-Type':'application/json', 'Authorization':('Bearer '+ api_key)}
    body = str.encode(json.dumps({
        "chat_input": types_str
    }))
    req = urllib.request.Request(api_url, body, headers)
    try:
        spinner = Halo(text='\nFiguring out the roles', spinner='dots', placement='right', interval=100)
        spinner.start()
        response = urllib.request.urlopen(req)
        spinner.succeed('Roles found')
        result = response.read().decode('utf-8')
        return parse_output(result)
    except urllib.error.HTTPError as error:
        print("The request failed with status code: " + str(error.code))
        spinner.fail('Failed to get roles')
        # Print the headers - they include the requert ID and the timestamp, which are useful for debugging the failure
        print(error.info())
        print(error.read().decode("utf8", 'ignore'))

def role_verifier(recommended_roles):
    actual_roles = []
    invalid_roles = []
    with open('roles-with-permissions.json') as f:
        builtin_roles = json.load(f)
        builtin_roles_map = {}
        for role in builtin_roles:
            builtin_roles_map[role['roleName']] = role
        for role in recommended_roles:
            if role in builtin_roles_map:
                actual_roles.append(role)
            else:
                invalid_roles.append(role)
    return actual_roles, invalid_roles


def get_roles(bicep_loc, is_git=False):
    api_details = get_creds()
    if is_git:
        with tempfile.TemporaryDirectory() as tmpdirname:
            spinner = Halo(text='\nCloning the repo in temp directory', spinner='dots', placement='right')
            spinner.start()
            subprocess.run(['git', 'clone', bicep_loc, tmpdirname], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            spinner.succeed("Cloning done")
            resource_types = parse_bicep(tmpdirname)
    else:
        resource_types = parse_bicep(bicep_loc)

    return get_gpt_roles(api_details, resource_types)

def app():
    parser = argparse.ArgumentParser(description='A command-line tool to get roles from a Bicep file or Git repository.')

    parser.add_argument('-d', '--directory', help="The local directory containing Bicep files.")
    parser.add_argument('-g', '--git', help="The git repo link containing Bicep files.")
    args = parser.parse_args()

    if args.git:
        bicep_loc = args.git
        is_git = True
    else:
        bicep_loc = args.directory
        is_git = False

    roles = get_roles(bicep_loc, is_git)
    _, invalid_roles = role_verifier(roles['roles'])

    print(Fore.GREEN + "\nRecommended roles provided by LLM:\n")
    print(Fore.CYAN + "\n".join(sorted(roles['roles'])))

    if len(invalid_roles) > 0:
        print(Fore.YELLOW + "\nOut of these follwoing are invalid roles\n")
        print(Fore.RED + "\n".join(sorted(invalid_roles)))


if __name__ == '__main__':
    app()
