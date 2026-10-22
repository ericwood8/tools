"""Probes AWS Bedrock with whatever credentials you have, and explains the failure. No boto3 and no AWS CLI call is needed to talk to AWS:
requests are signed here (Signature Version 4) or sent with a Bedrock API key (bearer token).

  python bedrock_probe.py whoami                                  who these credentials are (root, IAM user or role) and the account
  python bedrock_probe.py models --filter nova                    foundation models in the region, with ON_DEMAND or INFERENCE_PROFILE
  python bedrock_probe.py profiles --filter nova                  inference profile ids (the `us.` ids some models need)
  python bedrock_probe.py converse "Say hi in five words"         one Converse call (default model amazon.nova-micro-v1:0, 200 tokens)
  python bedrock_probe.py --self-test                             checks the signer against AWS's published test vector

Options: --region (default AWS_REGION, AWS_DEFAULT_REGION, then us-east-2), --model, --max-tokens, --system TEXT, --raw (print the JSON),
--auth auto|iam|bearer (auto tries IAM keys first), --profile NAME (AWS CLI profile), --user-secrets PROJECT_DIR.

Credential sources, in this order (the first one found is used and named, never printed in full):
  IAM keys:  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN;  the .NET user secrets of PROJECT_DIR;  `aws configure export-credentials`
  API key:   AWS_BEARER_TOKEN_BEDROCK;  the user secret Bedrock:ApiKey
User secret names are Bedrock:AiReviewer:AccessKey, Bedrock:AiReviewer:SecretAccessKey and Bedrock:ApiKey (--access-key-name, --secret-key-name
and --api-key-name change them). An API key works for models and converse, not for whoami. A converse call costs a fraction of a cent.
Exit code 0 when the call succeeded, 1 when AWS refused it, 2 for a problem with the arguments or the credentials.
"""
import argparse
import datetime
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DEFAULT_REGION = "us-east-2"
DEFAULT_MODEL = "amazon.nova-micro-v1:0"
TIMEOUT_SECONDS = 60


def fail(message, code=2):
    print(message, file=sys.stderr)
    sys.exit(code)


@dataclass
class Credentials:
    kind: str            # "iam" or "bearer"
    source: str
    access_key: str = ""
    secret_key: str = ""
    token: str = ""      # session token (iam) or API key (bearer)

    def describe(self):
        if self.kind == "bearer":
            return f"Bedrock API key (bearer token) from {self.source}"
        key = self.access_key
        shown = key[:4] + "..." + key[-4:] if len(key) > 8 else "..."
        return f"IAM access key {shown} from {self.source}" + (" with a session token" if self.token else "")


def hmac_sha256(key, text):
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).digest()


def sign_v4(method, url, body, extra_headers, region, service, creds, now=None):
    """Headers (Authorization, x-amz-date, session token) that sign this request. The path of url is already percent-encoded as it will be
    sent; the canonical request encodes it once more, as every service except S3 requires (a model id's ':' travels as %3A and is signed as %253A)."""
    parts = urllib.parse.urlsplit(url)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date, date = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    headers = {"host": parts.netloc, "x-amz-date": amz_date, **{k.lower(): v for k, v in (extra_headers or {}).items()}}
    if creds.token:
        headers["x-amz-security-token"] = creds.token
    query = sorted((urllib.parse.quote(k, safe="~"), urllib.parse.quote(v, safe="~")) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    names = sorted(headers)
    canonical = "\n".join([
        method, urllib.parse.quote(parts.path or "/", safe="/~"), "&".join(f"{k}={v}" for k, v in query),
        "".join(f"{n}:{headers[n].strip()}\n" for n in names), ";".join(names), hashlib.sha256(body).hexdigest()])
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    key = ("AWS4" + creds.secret_key).encode("utf-8")
    for part in (date, region, service, "aws4_request"):
        key = hmac_sha256(key, part)
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    signed = {k: v for k, v in headers.items() if k != "host"}
    signed["Authorization"] = f"AWS4-HMAC-SHA256 Credential={creds.access_key}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"
    return signed


def user_secrets(project):
    result = subprocess.run(["dotnet", "user-secrets", "list", "--project", project], capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"dotnet user-secrets failed for {project}: " + (result.stderr or result.stdout).strip()[:200])
    found = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^(.+?) = (.*)$", line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def cli_credentials(profile):
    command = ["aws", "configure", "export-credentials", "--format", "process"] + (["--profile", profile] if profile else [])
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    return Credentials("iam", "the AWS CLI profile" + (f" {profile}" if profile else ""), data["AccessKeyId"], data["SecretAccessKey"], data.get("SessionToken", ""))


def find_credentials(args):
    secrets = user_secrets(args.user_secrets) if args.user_secrets else {}
    iam, bearer = [], []
    env = os.environ
    if env.get("AWS_ACCESS_KEY_ID") and env.get("AWS_SECRET_ACCESS_KEY"):
        iam.append(lambda: Credentials("iam", "environment variables", env["AWS_ACCESS_KEY_ID"], env["AWS_SECRET_ACCESS_KEY"], env.get("AWS_SESSION_TOKEN", "")))
    if secrets.get(args.access_key_name) and secrets.get(args.secret_key_name):
        iam.append(lambda: Credentials("iam", "user secrets", secrets[args.access_key_name], secrets[args.secret_key_name]))
    iam.append(lambda: cli_credentials(args.profile))
    if env.get("AWS_BEARER_TOKEN_BEDROCK"):
        bearer.append(lambda: Credentials("bearer", "AWS_BEARER_TOKEN_BEDROCK", token=env["AWS_BEARER_TOKEN_BEDROCK"]))
    if secrets.get(args.api_key_name):
        bearer.append(lambda: Credentials("bearer", "user secrets", token=secrets[args.api_key_name]))
    order = {"iam": iam, "bearer": bearer, "auto": iam + bearer}[args.auth]
    for make in order:
        creds = make()
        if creds:
            return creds
    fail("no credentials found: set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, or AWS_BEARER_TOKEN_BEDROCK, or pass --user-secrets PROJECT_DIR, "
         "or run `aws configure`")


def call(method, url, body, region, service, creds, content_type="application/json", accept="application/json"):
    headers = {"Content-Type": content_type, "Accept": accept}
    if creds.kind == "bearer":
        headers["Authorization"] = "Bearer " + creds.token
    else:
        headers.update(sign_v4(method, url, body, {"content-type": content_type}, region, service, creds))
    request = urllib.request.Request(url, data=body if method != "GET" else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8", errors="replace"), {}
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace"), dict(error.headers)
    except urllib.error.URLError as error:
        fail(f"cannot reach {urllib.parse.urlsplit(url).netloc}: {error.reason}")


HINTS = [
    (r"not allowed for this account", "An account level block on Bedrock (not an IAM policy: the same text appears for the root user). Open an AWS Support case "
        "(Account and billing, or Service limit increase for Bedrock) and ask for model access on the account; also check the account has a valid payment method."),
    (r"on-demand throughput isn.t supported|inference profile", "This model must be called through an inference profile: use the id from `profiles` "
        "(for example us.amazon.nova-micro-v1:0) as --model."),
    (r"is not authorized to perform", "IAM refuses the action. The message names the principal and the action: attach a policy that allows it "
        "(bedrock:InvokeModel and bedrock:Converse for the model, bedrock:ListFoundationModels to list)."),
    (r"model identifier is invalid|could not resolve the foundation model|ResourceNotFound", "The model id is wrong or not offered in this region: "
        "run `models --filter <name>` for this region."),
    (r"SignatureDoesNotMatch|InvalidSignature|signature we calculated", "The secret key is wrong, or this computer's clock is more than a few minutes off."),
    (r"UnrecognizedClient|security token included in the request is invalid|InvalidClientTokenId", "The access key id is unknown or deleted, or a session token is missing or expired."),
    (r"ThrottlingException|Too many requests", "Rate or quota limit: wait and retry, or ask for a quota increase."),
    (r"ExpiredToken|expired", "The credentials or the API key expired: create a new one."),
    (r"api key|bearer", "The Bedrock API key was refused: check it is complete, not expired, and for this region's account."),
]


def explain_failure(status, text):
    try:
        data = json.loads(text)
        message = data.get("message") or data.get("Message") or text
    except ValueError:
        message = re.sub(r"<[^>]+>", " ", text)
    message = re.sub(r"\s+", " ", message).strip()
    print(f"AWS answered {status}: {message[:600]}", file=sys.stderr)
    for pattern, hint in HINTS:
        if re.search(pattern, text, re.I):
            print("meaning: " + hint, file=sys.stderr)
            break


def classify_arn(arn):
    if arn.endswith(":root"):
        return "the ROOT user of the account (use an IAM user for anything but account setup)"
    if ":user/" in arn:
        return "IAM user " + arn.split(":user/")[-1]
    if ":assumed-role/" in arn:
        return "a role session (" + arn.split(":assumed-role/")[-1] + ")"
    return "an unrecognised principal type"


def run_command(args):
    creds = find_credentials(args)
    print("credentials: " + creds.describe(), flush=True)
    region = args.region

    if args.command == "whoami":
        if creds.kind == "bearer":
            fail("whoami needs IAM keys: a Bedrock API key cannot call STS (use --auth iam)")
        status, text, _ = call("POST", f"https://sts.{region}.amazonaws.com/", b"Action=GetCallerIdentity&Version=2011-06-15", region, "sts", creds,
                               "application/x-www-form-urlencoded", "text/xml")
        if status != 200:
            explain_failure(status, text)
            return 1
        field = lambda tag: (re.search(rf"<{tag}>(.*?)</{tag}>", text) or [None, ""])[1]
        print(f"account: {field('Account')}\narn:     {field('Arn')}\nwho:     {classify_arn(field('Arn'))}")
        return 0

    if args.command in ("models", "profiles"):
        path, key = ("/foundation-models", "modelSummaries") if args.command == "models" else ("/inference-profiles?maxResults=1000", "inferenceProfileSummaries")
        status, text, _ = call("GET", f"https://bedrock.{region}.amazonaws.com{path}", b"", region, "bedrock", creds)
        if status != 200:
            explain_failure(status, text)
            return 1
        rows = json.loads(text).get(key, [])
        needle = (args.filter or "").lower()
        shown = 0
        for row in sorted(rows, key=lambda r: r.get("modelId") or r.get("inferenceProfileId")):
            if args.command == "models":
                line = (f"{row['modelId']} | {row.get('providerName', '')} | {','.join(row.get('inputModalities', []))} -> "
                        f"{','.join(row.get('outputModalities', []))} | {','.join(row.get('inferenceTypesSupported', []))}")
            else:
                line = f"{row['inferenceProfileId']} | {row.get('inferenceProfileName', '')} | {row.get('type', '')} | {row.get('status', '')}"
            if needle in line.lower():
                print(line)
                shown += 1
        print(f"{shown} of {len(rows)} in {region}")
        return 0

    model = urllib.parse.quote(args.model, safe="")
    request = {"messages": [{"role": "user", "content": [{"text": args.prompt}]}], "inferenceConfig": {"maxTokens": args.max_tokens, "temperature": 0.2}}
    if args.system:
        request["system"] = [{"text": args.system}]
    status, text, _ = call("POST", f"https://bedrock-runtime.{region}.amazonaws.com/model/{model}/converse", json.dumps(request).encode("utf-8"), region, "bedrock", creds)
    if status != 200:
        explain_failure(status, text)
        return 1
    data = json.loads(text)
    if args.raw:
        print(json.dumps(data, indent=2))
        return 0
    reply = "".join(block.get("text", "") for block in data.get("output", {}).get("message", {}).get("content", []))
    usage = data.get("usage", {})
    print(f"\n{reply}\n\nmodel={args.model} region={region} stop={data.get('stopReason')} tokens in/out={usage.get('inputTokens')}/{usage.get('outputTokens')} "
          f"latency={data.get('metrics', {}).get('latencyMs')} ms")
    return 0


def self_test():
    failed = 0

    def check(name, got, expected):
        nonlocal failed
        if got != expected:
            failed += 1
            print(f"FAIL {name}\n  expected {expected}\n  got      {got}")

    vector = Credentials("iam", "test", "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
    signed = sign_v4("GET", "https://example.amazonaws.com/", b"", None, "us-east-1", "service", vector, datetime.datetime(2015, 8, 30, 12, 36, tzinfo=datetime.timezone.utc))
    check("AWS get-vanilla signature", signed["Authorization"],
          "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, SignedHeaders=host;x-amz-date, "
          "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31")
    check("session token is signed", "x-amz-security-token" in sign_v4("GET", "https://a.b/", b"", None, "r", "s", Credentials("iam", "t", "K", "S", "TOKEN")), True)
    check("root arn", classify_arn("arn:aws:iam::123456789012:root").startswith("the ROOT user"), True)
    check("user arn", classify_arn("arn:aws:iam::123456789012:user/AiReviewer"), "IAM user AiReviewer")
    check("model id path", urllib.parse.quote("us.amazon.nova-micro-v1:0", safe=""), "us.amazon.nova-micro-v1%3A0")
    check("masked key", Credentials("iam", "x", "AKIAABCDEFGHIJKLMNOP", "s").describe(), "IAM access key AKIA...MNOP from x")
    print("all checks passed" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["whoami", "models", "profiles", "converse"])
    p.add_argument("prompt", nargs="?", help="the text to send (converse)")
    p.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--max-tokens", type=int, default=200)
    p.add_argument("--system")
    p.add_argument("--filter")
    p.add_argument("--raw", action="store_true")
    p.add_argument("--auth", choices=["auto", "iam", "bearer"], default="auto")
    p.add_argument("--profile")
    p.add_argument("--user-secrets", metavar="PROJECT_DIR")
    p.add_argument("--access-key-name", default="Bedrock:AiReviewer:AccessKey")
    p.add_argument("--secret-key-name", default="Bedrock:AiReviewer:SecretAccessKey")
    p.add_argument("--api-key-name", default="Bedrock:ApiKey")
    args = p.parse_args()
    if args.command == "converse" and not args.prompt:
        fail("converse needs a prompt: bedrock_probe.py converse \"your text\"")
    sys.exit(run_command(args))


if __name__ == "__main__":
    main()
