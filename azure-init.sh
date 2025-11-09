az ad sp create-for-rbac \
  --name "terraform-automation" \
  --role "Contributor" \
  --scopes /subscriptions/63cdb0cd-930f-4664-b489-b30ac48a5f1e
