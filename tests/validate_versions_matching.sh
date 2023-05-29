# This script checks whether the appVersion in the helm cahrt matches the latest tag in the git repo
# It is used to ensure that the appVersion is updated when a new release is created

git_latest_tag=$(git describe --tags --abbrev=0)
helm_chart_appversion=$(cat helm/chart/Chart.yaml | grep appVersion | awk '{print "v" $2}')

if [ "$git_latest_tag" != "$helm_chart_appversion" ]; then
  echo "The appVersion in the helm chart does not match the latest git tag"
  echo "Latest git tag: $git_latest_tag"
  echo "appVersion in helm chart: $helm_chart_appversion"
  exit 1
fi
