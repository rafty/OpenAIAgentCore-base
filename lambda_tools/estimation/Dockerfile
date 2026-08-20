FROM public.ecr.aws/lambda/python:3.12

COPY lambda_tools/estimation/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN python -m pip install --no-cache-dir --requirement ${LAMBDA_TASK_ROOT}/requirements.txt

COPY lambda_tools ${LAMBDA_TASK_ROOT}/lambda_tools

CMD ["lambda_tools.estimation.handler.lambda_handler"]
