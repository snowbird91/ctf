---
layout: post
title: "How I Built the Infrastructure for L3akCTF 2026"
categories: [infrastructure, l3akctf2026]
date: 2026-09-01 12:00:00 -0400
blog_post: true
mermaid: true
permalink: /blog/l3akctf-2026-infrastructure/
---

I was the main infrastructure lead for L3akCTF 2026!

L3akCTF 2026 was a two-day event, starting at 18:00 UTC on July 31 and ending at 18:00 UTC on August 2. 

**TL;DR**: the infrastructure was very successful! In this write-up, I'll go into the finer details of how everything was set up behind the scenes, along with some reflections.

## Starting from scratch

The Google Cloud project was created around July 10. When I first looked through everything, the project was basically empty.

The infrastructure from previous years was not feasible to reuse because of numerous issues. Essentially, we were starting completely from scratch.

The project's global CPU quota was only 32 vCPUs. At the same time, we expected a lot of teams, and several challenges needed a separate instance for every team. The risk of not having enough quota lived rent-free in my brain until the CTF ended.

## What infrastructure did we use?

The main question was: what CTF infrastructure should we use?

There are lots of options out there, such as CTFd, kCTF, and others. CTFd is one of the biggest platforms, but common issues with the system caused major problems last year.

Luckily, while participating in DiceCTF Quals in March 2026, I got to experience the beautiful, revamped [rCTF v2](https://github.com/otter-sec/rctf) infrastructure. The original release of rCTF was made by redpwn in 2020. Later, OtterSec took over maintenance. We decided to reach out to es3n1n (absolute GOAT) to see if we could get early access to rCTF v2 for the CTF, since it had not been publicly released when we began setting up the infrastructure. To our relief, es3n1n agreed to let us use it and also offered to assist with anything. es3n1n, thank you again!

## Architecture decisions

The easiest option would have been putting rCTF, PostgreSQL, Redis, and every challenge inside one Kubernetes cluster. However, some challenges were intentionally vulnerable. Some gave players arbitrary code execution, some gave root inside a container, and some required unusual capabilities. We decided to keep the scoreboard database separate.

The infrastructure was split into two major parts:

1. A platform VM for rCTF, PostgreSQL, Redis, the admin bot, and Nginx.
2. A separate GKE cluster for challenge workloads.

<pre class="mermaid">
flowchart LR
    P[Players] --> CF[Cloudflare]

    CF --> NX[Nginx]
    NX --> R[rCTF]
    R --> PG[(PostgreSQL)]
    R --> RD[(Redis)]
    R --> AB[Admin bot]

    R --> OP[rCTF Kubernetes operator]
    GH[GitHub Actions + Konata] --> AR[Artifact Registry]
    GH --> OP

    P --> T[Traefik]
    T --> S[Shared services]
    T --> J[Shared pwn jails]
    T --> I[Per-team instances]

    AR --> S
    AR --> J
    AR --> I
</pre>

## Google Cloud foundation

Once I knew what I wanted, I started setting up the cloud project.

### IAM and service accounts

Separate service accounts were created for:

- the platform VM
- GKE nodes
- GitHub deployments
- other narrow operational tasks

### Networking

Next, I deleted the default VPC and its default firewall rules.

I created a custom VPC with separate platform and GKE subnets, secondary ranges for Kubernetes pods and Services, and Cloud NAT for the private workers. The GKE cluster used private nodes and a private control plane.

The final cluster configuration had:

- VPC-native networking
- Dataplane V2
- Workload Identity
- Shielded Nodes and Secure Boot
- NodeLocal DNS
- managed Prometheus

The platform VM eventually had a public origin address, but Nginx and the firewall accepted public web traffic only from Cloudflare's published IP ranges. Nginx then restored the actual player IP using CF-Connecting-IP.

## Capacity and quota

While setting everything up, I calculated how much quota I would need, considering shared services, per-team instances, the platform VM, and other resources.

The final plan fit inside a 100-vCPU global quota:

- five e2-standard-16 general workers
- two e2-standard-4 shared-jail workers
- one four-vCPU platform VM
- standard Persistent Disk for workers

This led to a ceiling of 92 vCPUs and left a very small operating margin. I was extremely cautious and nervous about our resource usage. Services can sometimes go down when hammered, and I had almost no wiggle room to scale them up.

## Choosing the cluster shape

Initially, we decided to set everything up in us-central1. However, we soon realized there was not enough capacity. Per es3n1n's recommendation, we migrated to europe-west1, which had plenty of capacity.

Afterward, I tested both major connection types.

For web challenges:

```text
player -> Cloudflare/DNS -> Traefik HTTPS -> challenge Service -> pod
```

For TCP challenges:

```text
player -> ncat --ssl host 1337 -> Traefik TCP TLS -> challenge pod
```

Great! At this point, we had proven HTTPS, TCP-over-TLS, wildcard certificates, private nodes, metadata blocking, default-deny egress, setuid behavior, and expired-instance cleanup.

## Workload classification

I went through the challenge repository and classified challenges as:

- offline/handout only
- shared service
- per-team instance
- special external service

Why did this matter so much?

Imagine a normal web challenge with user accounts and a mutable database. If every team shares it, one team can modify another team's state. That probably needs per-team instances.

Now imagine a pwn service where every incoming connection gets its own fresh nsjail process. The listener pod can be shared because connection-level isolation already exists.

That alone can remove hundreds of Kubernetes pods, freeing up more resources.

### Shared pwn jails

We converted seven high-risk services to shared pwn.red/jail listeners.

The listener remained shared, but every connection entered its own short-lived nsjail.

These privileged jail services could not safely run beside ordinary challenges. I created a separate shared-jails namespace and a dedicated e2-standard-4 node pool.

Normal challenge pods could not accidentally schedule onto the jail workers, and privileged jail pods could not drift onto the general workers. This preserved scheduling isolation between the two workload types.

### Recalculating the quota

After recalculating requests, one copy of every challenge that was then instanced requested roughly:

- 3.3 CPU cores
- 4 GiB of memory
- 4.25 GiB of temporary storage

The rounded average was about 275 millicores and 384 MiB of memory per active instance.

Using realistic active-team scenarios gave approximately:

- 190 likely active instances
- 317 normal-load instances
- 397 stress instances

After the shared-jail conversion, the planned ceiling became:

| Resource | Maximum | vCPUs |
|---|---:|---:|
| General challenge workers | 5 × e2-standard-16 | 80 |
| Shared-jail workers | 2 × e2-standard-4 | 8 |
| Platform VM | 1 × 4-vCPU VM | 4 |
| **Total** |  | **92** |

Our approved quota was 100 vCPUs. Nice! It was tight, but it fit.

### Worker storage

The GKE workers used standard Persistent Disk. The project had 4,096 GB of standard-disk quota, and the maximum worker layout needed around 850 GB.

## Konata: where are all the source files?

Around this time, we created the Konata repository. [Konata](https://github.com/project-sekai-ctf/konata) is a CTF tool created by Project Sekai to manage challenges and deploy them across different CTF platforms. It's inspired by rCDS, made by redpwn.

The Konata repository did not contain every challenge's source or player files. Those stayed in the private challenge repository.

Each Konata overlay described how to turn one challenge directory into:

- an rCTF record
- an attachment
- an image build
- a shared Deployment
- or a per-team instancer configuration

During deployment, GitHub Actions checked out both repositories and combined them:

```text
Konata overlay + private challenge source -> staged challenge directory -> kona sync
```

We created a deployment workflow that used Workload Identity to push images and reach GKE.

## Large handouts

Some challenge handouts were too large for normal Git. GitHub rejects regular files above 100 MB, and a few challenges involved files above that limit. I used a GCS bucket with content-addressed paths:

```text
uploads/<sha256>/<filename>
```

Much larger forensic handouts later used the same pattern.

## rCTF v2.1.2 and signed flags

Before the CTF started, rCTF v2.1.2 was released with dynamic signed-flag support. We decided to implement it as a useful way to catch teams sharing flags. You can read more about how it works [here](https://rctf.osec.io/providers/flags/).

## Root-only dynamic flags

Several challenges needed the player process to be unable to read the flag directly. The intended exploit would eventually reach a setuid /readflag helper.

I used the same pattern across these challenges:

1. rCTF generated the team flag.
2. The operator placed it in a pod annotation.
3. A root init container read the annotation through Kubernetes's downward API.
4. The init container wrote the flag into a memory-backed emptyDir.
5. It set the file to root ownership and mode 0400.
6. The main container mounted it read-only.

```yaml
volumes:
  - name: flag
    emptyDir:
      medium: Memory
      sizeLimit: 1Mi
```

## GeoSINT

GeoSINT was intentionally a shared service. Eight static OSINT locations were linked to one web app, and the application kept the private answers separate from the public panorama assets.

The deployment included:

- one namespace
- two replicas behind a ClusterIP Service
- one Traefik HTTPS route
- a private Secret for answer coordinates and flags
- a request rate limit
- a normal public HTTPS route, with static rCTF records linking to the shared service

## How was AI usage detected?

We borrowed the US Cyber Games' method of injecting a response header that asked AI or autonomous agents to identify themselves with `X-Llm-Id` on future requests. We then retained `User-Agent` and `X-Llm-Id` in access logs and set up a bot to send a notification automatically when the request header was detected.

This was set up only for instanced web challenges, so we could trace each incident back to the challenge and team. It worked very well, and we had over 500 flagged incidents.

## Investigating team sharing

rCTF retained the IP used for each flag submission, so I wrote a script that output:

- overlapping teams
- event counts
- correct-submission counts
- first and last timestamps

However, this method wasn't 100% reliable. University networks were a major issue because unrelated teams could appear under the same public address. Teams that were incorrectly banned were all reinstated after appealing.

## The event by the numbers

### rCTF records

| rCTF record | Count |
|---|---:|
| User/team records | 1,225 |
| User/team records with a score | 710 |
| Banned teams in the August 4 snapshot | 269 |
| Challenge records | 77 |
| Solves | 7,042 |
| Submission logs | 19,442 |
| Correct submissions | 6,986 |
| Incorrect submissions | 12,346 |
| Cheated submissions | 46 |
| Already-solved submissions | 64 |
| Score events | 268,904 |

### How much did this cost?

| Service | Gross event cost |
|---|---:|
| Cloud Storage | $104.42 |
| Compute Engine | $97.40 |
| Kubernetes Engine | $3.40 |
| Networking | $3.33 |
| Cloud Monitoring | $0.99 |
| Artifact Registry | $0.10 |
| Secret Manager | $0.05 |
| Cloud Logging | $0.00 |
| BigQuery | $0.00 |
| **Gross event usage** | **$209.69** |
| Credits applied | **-$209.69** |
| **Net billed** | **$0.00** |

## Takeaways

- Start early! Begin planning your CTF ahead of time, and begin infrastructure setup more than a month before the CTF starts. Many unexpected things and roadblocks can arise; be prepared to handle them.
- If your infrastructure is sponsored by Google Cloud, make sure you know how much quota you have and whether it will be enough. Increasing quotas was a massive headache. I even got routed to a premium provider and pitched services I did not need for over an hour on a call.
- Playtest your challenges on the infrastructure. There may be unintended solutions or simple misconfigurations that become issues when the CTF is live.
- Be smart about how things are set up! Properly using per-team instances, nsjail listeners, and similar tools can save lots of resources and unnecessary costs.
- Learn something new and have fun!

L3akCTF 2026 was undoubtedly a massive success. The CTF stayed up (my number one goal was to make sure the infrastructure didn't go down), players solved challenges, and the platform and its data remained available throughout the event. I'll take that as a win!

Thank you to the other supportive organizers and talented authors. Big thanks to es3n1n for supporting us every step of the way. I learned a ridiculous amount while building and operating this project, and it was an extremely fun system to work on.

If you have any further questions, feel free to shoot me a DM.

Thank you for reading, and have a great day!
