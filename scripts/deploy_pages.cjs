/* Use upload-pages-artifact's ID directly; artifact-service discovery can return
 * an empty list even after the upload has finalized successfully. */
module.exports = async function deployPages({github, context, core, artifactId,
  wait = ms => new Promise(resolve => setTimeout(resolve, ms)), timeout = 600000}) {
  if (!/^\d+$/.test(String(artifactId)) || !Number.isSafeInteger(Number(artifactId)) || Number(artifactId) <= 0)
    throw new Error('Missing or invalid uploaded Pages artifact ID');
  const {data: deployment} = await github.request('POST /repos/{owner}/{repo}/pages/deployments', {
    ...context.repo, artifact_id: Number(artifactId), pages_build_version: context.sha,
    oidc_token: await core.getIDToken()
  });
  const id = deployment.id || deployment.status_url?.split('/').pop();
  if (!id) throw new Error('Pages did not return a deployment ID');
  core.info(`Publishing artifact ${artifactId}, deployment ${id}`);
  const params = {...context.repo, pages_deployment_id: id};
  const failures = new Set(['deployment_failed', 'deployment_perms_error', 'deployment_content_failed',
    'deployment_cancelled', 'deployment_lost']);
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await wait(5000);
    const {data} = await github.request('GET /repos/{owner}/{repo}/pages/deployments/{pages_deployment_id}', params);
    core.info(`Pages status: ${data.status}`);
    if (data.status === 'succeed') {
      core.setOutput('page_url', deployment.page_url);
      return;
    }
    if (failures.has(data.status)) throw new Error(`Pages deployment failed: ${data.status}`);
  }
  await github.request('POST /repos/{owner}/{repo}/pages/deployments/{pages_deployment_id}/cancel', params);
  throw new Error('Pages deployment timed out after 10 minutes');
};
