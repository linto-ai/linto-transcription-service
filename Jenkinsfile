def notifyLintoDeploy(service_name, tag, commit_sha) {
    echo "Notifying linto-deploy for ${service_name}:${tag} (commit: ${commit_sha})..."
    withCredentials([usernamePassword(
        credentialsId: 'linto-deploy-bot',
        usernameVariable: 'GITHUB_APP',
        passwordVariable: 'GITHUB_TOKEN'
    )]) {
        writeFile file: 'payload.json', text: "{\"event_type\":\"update-service\",\"client_payload\":{\"service\":\"${service_name}\",\"tag\":\"${tag}\",\"commit_sha\":\"${commit_sha}\"}}"
        sh 'curl -s -X POST -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/vnd.github.v3+json" -d @payload.json https://api.github.com/repos/linto-ai/linto-deploy/dispatches'
    }
}

pipeline {
    agent any
    environment {
        DOCKER_HUB_REPO = "lintoai/linto-transcription-service"
        DOCKER_HUB_CRED = 'docker-hub-credentials'
        VERSION = ''
    }

    stages{
        stage('Docker build for master branch'){
            when{
                branch 'master'
            }
            steps {
                echo 'Publishing latest'
                script {
                    def commit_sha = sh(returnStdout: true, script: 'git rev-parse HEAD').trim()

                    image = docker.build(env.DOCKER_HUB_REPO)
                    VERSION = sh(
                        returnStdout: true,
                        script: "awk -v RS='' '/#/ {print; exit}' RELEASE.md | head -1 | sed 's/#//' | sed 's/ //'"
                    ).trim()

                    docker.withRegistry('https://registry.hub.docker.com', env.DOCKER_HUB_CRED) {
                        image.push("${VERSION}")
                        image.push('latest')
                    }

                    notifyLintoDeploy('linto-transcription-service', VERSION, commit_sha)
                }
            }
        }

        stage('Docker build for next (unstable) branch'){
            when{
                branch 'next'
            }
            steps {
                echo 'Publishing unstable'
                script {
                    image = docker.build(env.DOCKER_HUB_REPO)

                    docker.withRegistry('https://registry.hub.docker.com', env.DOCKER_HUB_CRED) {
                        image.push('latest-unstable')
                    }
                }
            }
        }

        // TEMPORARY: Build slim and alpine variants for testing
        stage('Build slim and alpine variants'){
            when{
                branch 'feature/slim-alpine-images'
            }
            steps {
                echo 'Building slim and alpine variants for testing'
                script {
                    def slim = docker.build("${env.DOCKER_HUB_REPO}", "-f Dockerfile.slim .")
                    def alpine = docker.build("${env.DOCKER_HUB_REPO}", "-f Dockerfile.alpine .")

                    docker.withRegistry('https://registry.hub.docker.com', env.DOCKER_HUB_CRED) {
                        slim.push('slim-test')
                        alpine.push('alpine-test')
                    }
                }
            }
        }
    }// end stages
}
