# The MCP endpoint cfo.ai reads

cfo.ai is a hosted service, so it needs a public HTTPS URL for the telemetry
server. That ran through a `trycloudflare` tunnel for most of the build, which
hands out a new hostname every restart — the connection had to be re-made in
cfo.ai four times. It now runs on the hackathon AWS account instead, on a
stable URL.

| | |
|---|---|
| Endpoint | `https://44-198-170-139.sslip.io/mcp` |
| Auth | `X-API-Key` header |
| Instance | `i-06196a09ecfbe54b1`, t3.micro, us-east-1a |
| VPC / subnet | `Hackathon_VPC-vpc` / `subnet-04afa246ac9928721` (public) |
| Security group | `sg-0a76c39d6164a5a27` — 80, 443, 22 |
| Disk | 20 GB gp3 (limit is 50 GB) |

`sslip.io` resolves `44-198-170-139.sslip.io` to that IP, which lets Caddy get
a real Let's Encrypt certificate without owning a domain. Caddy terminates TLS
and proxies to the server on `127.0.0.1:8787`, so the server itself is never
exposed. The API key is passed to systemd, not committed.

## Operating it

```bash
ssh -i ~/.ssh/upshift-user104.pem ubuntu@44.198.170.139
sudo systemctl status upshift-mcp caddy
sudo journalctl -u upshift-mcp -f
```

Both units are enabled at boot and the server restarts on failure, so it
survives a reboot. **Stopping and starting the instance reassigns the public
IP**, which changes the hostname and invalidates the certificate — reboot
instead, or redeploy with the new IP.

## Refreshing the evidence it serves

The server reads run records from its own copy. After new runs:

```bash
tar czf /tmp/ev.tgz evidence/runs evidence/ablation.json
scp -i ~/.ssh/upshift-user104.pem /tmp/ev.tgz ubuntu@44.198.170.139:/opt/upshift/
ssh -i ~/.ssh/upshift-user104.pem ubuntu@44.198.170.139 \
  'cd /opt/upshift && tar xzf ev.tgz && rm ev.tgz && sudo systemctl restart upshift-mcp'
```

## Shutting down

One instance per user is allowed, so terminate rather than leaving it idle:

```bash
AWS_PROFILE=hackathon python -c "
import boto3; boto3.client('ec2','us-east-1').terminate_instances(InstanceIds=['i-06196a09ecfbe54b1'])"
```

## Account notes

- us-east-1 only; EC2, Lambda, IAM roles and load balancers only.
- `ec2:CreateTags` is denied by a service control policy, so the instance
  could not be tagged at launch; the account's own automation applies
  `CreatedBy`.
- `ssm:GetParameter` is denied too, so the Ubuntu AMI was resolved through
  `ec2:DescribeImages` against Canonical's owner id rather than the usual SSM
  public parameter.
- The account is shared with other participants. Ten instances belonging to
  other users were running at deploy time and none were touched.
