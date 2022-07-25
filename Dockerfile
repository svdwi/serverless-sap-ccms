FROM public.ecr.aws/lambda/python:3.9

# Install OS dependencies
RUN yum update -y \
    && yum install -y \
    gcc \
    gcc-c++

# Copy and Set nwrfcsdk
COPY ./resources/nwrfcsdk ${LAMBDA_TASK_ROOT}/resources/nwrfcsdk
ENV SAPNWRFC_HOME ${LAMBDA_TASK_ROOT}/resources/nwrfcsdk
ENV LD_LIBRARY_PATH ${SAPNWRFC_HOME}/lib

# Set location for dev_rfc.log
ENV RFC_TRACE_DIR /tmp

# Install the function's dependencies using poetry
RUN pip install poetry cython
RUN poetry config virtualenvs.create false
COPY pyproject.toml ${LAMBDA_TASK_ROOT}
COPY poetry.lock ${LAMBDA_TASK_ROOT}
RUN poetry install

# Copy app codes
COPY lambda_app ${LAMBDA_TASK_ROOT}/lambda_app


CMD [ "lambda_app.handler.ccms.handler" ]