const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');

test('Pages uses the uploaded artifact ID even when artifact discovery is empty', async () => {
  const deploy = require('./deploy_pages.cjs');
  const calls = [], outputs = {};
  const github = {request: async (route, params) => {
    calls.push([route, params]);
    if (route === 'POST /repos/{owner}/{repo}/pages/deployments')
      return {data: {id: 72, page_url: 'https://example.github.io/site/'}};
    if (route === 'GET /repos/{owner}/{repo}/pages/deployments/{pages_deployment_id}')
      return {data: {status: 'succeed'}};
    throw new Error('Unexpected discovery request: ' + route);
  }};
  await deploy({github, context: {repo: {owner: 'example', repo: 'site'}, sha: 'abc'},
    core: {getIDToken: async () => 'oidc', info() {}, setOutput: (key,value) => outputs[key] = value},
    artifactId: '14875830740', wait: async () => {}});
  assert.equal(calls[0][1].artifact_id, 14875830740);
  assert.equal(outputs.page_url, 'https://example.github.io/site/');
  const workflow = readFileSync('.github/workflows/sync-mods.yml', 'utf8');
  assert.match(workflow, /steps\.pages_artifact\.outputs\.artifact_id/);
});

test('a failed Pages deployment fails the workflow', async () => {
  const deploy = require('./deploy_pages.cjs');
  await assert.rejects(deploy({
    github: {request: async route => ({data: route.startsWith('POST') ? {id: 73} : {status: 'deployment_content_failed'}})},
    context: {repo: {owner: 'example', repo: 'site'}, sha: 'abc'},
    core: {getIDToken: async () => 'oidc', info() {}, setOutput() {}}, artifactId: '123', wait: async () => {}
  }), /deployment_content_failed/);
});
