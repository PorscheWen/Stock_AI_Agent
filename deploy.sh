#!/bin/bash
# Stock_AI_agent — Google Cloud Run Job 部署腳本
# 執行前請先確認已登入：gcloud auth login && gcloud auth configure-docker asia-east1-docker.pkg.dev

set -e

PROJECT_ID="stock-ai-agent-prod"
REGION="asia-east1"                      # 台灣最近節點（台灣）
REPO="stock-ai"                          # Artifact Registry repo 名稱
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/stock-ai-agent:latest"
JOB_NAME="stock-ai-agent"

echo "=== 建立 Artifact Registry (若不存在) ==="
gcloud artifacts repositories create $REPO \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT_ID 2>/dev/null || true

echo "=== 使用 Cloud Build 建置並推送 Docker Image ==="
gcloud builds submit . \
  --tag=$IMAGE \
  --project=$PROJECT_ID

echo "=== 部署 Cloud Run Job ==="
gcloud run jobs deploy $JOB_NAME \
  --image=$IMAGE \
  --region=$REGION \
  --project=$PROJECT_ID \
  --task-timeout=30m \
  --max-retries=1 \
  --set-env-vars="LINE_CHANNEL_SECRET=${LINE_CHANNEL_SECRET}" \
  --set-env-vars="LINE_CHANNEL_ACCESS_TOKEN=${LINE_CHANNEL_ACCESS_TOKEN}" \
  --set-env-vars="LINE_USER_ID=${LINE_USER_ID}" \
  --set-env-vars="ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"

echo "=== 建立 Cloud Scheduler 排程 ==="
# 台灣時間 14:30（週一至週五）= UTC 06:30
gcloud scheduler jobs create http stock-ai-agent-trigger \
  --location=$REGION \
  --schedule="30 6 * * 1-5" \
  --time-zone="UTC" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/$JOB_NAME:run" \
  --http-method=POST \
  --oauth-service-account-email="$PROJECT_ID-compute@developer.gserviceaccount.com" \
  --project=$PROJECT_ID 2>/dev/null || \
gcloud scheduler jobs update http stock-ai-agent-trigger \
  --location=$REGION \
  --schedule="30 6 * * 1-5" \
  --project=$PROJECT_ID

echo ""
echo "✅ 部署完成！"
echo "   Cloud Run Job: $JOB_NAME"
echo "   排程：每週一~五 台灣時間 14:30"
echo ""
echo "手動觸發測試："
echo "  gcloud run jobs execute $JOB_NAME --region=$REGION --project=$PROJECT_ID"
