# set object lifecycle for openstates-realtime-bills s3 bucket: deletion after 2 days
aws s3api put-lifecycle-configuration --bucket openstates-realtime-bills --lifecycle-configuration '{
  "Rules": [
    {
      "Status": "Enabled",
      "Filter": {
        "Prefix": ""
      },
      "Expiration": {
        "Days": 2
      },
      "ID": "Delete after 2 days"
    }
  ]
}'