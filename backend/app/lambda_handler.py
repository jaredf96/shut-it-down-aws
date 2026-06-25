"""AWS Lambda entrypoint.

Wraps the FastAPI app with Mangum so it can run behind API Gateway / Lambda
Function URLs. Deploy the container image (see backend/Dockerfile) to Lambda and
set the handler to `app.lambda_handler.handler`.
"""

from mangum import Mangum

from app.main import app

handler = Mangum(app)
