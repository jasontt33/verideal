#!/bin/bash


aws ecr get-login-password --region us-east-1 --profile personal | docker login --username AWS --password-stdin 139595704459.dkr.ecr.us-east-1.amazonaws.com


docker build -t verideal/static-interest-page .

docker tag verideal/static-interest-page:latest 139595704459.dkr.ecr.us-east-1.amazonaws.com/verideal/static-interest-page:latest

docker push 139595704459.dkr.ecr.us-east-1.amazonaws.com/verideal/static-interest-page:latest