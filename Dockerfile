FROM v2fly/v2fly-core

RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

RUN mkdir -p /usr/local/V2RayPi
COPY . /usr/local/V2RayPi

RUN set -ex \
	&& apk add linux-headers wget gcc g++ python3 python3-dev openssl ca-certificates supervisor \
	&& wget https://bootstrap.pypa.io/get-pip.py \
	&& python3 get-pip.py \
	&& pip3 install -r /usr/local/V2RayPi/script/requirements.txt -i http://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com \
	&& apk del wget gcc g++ python3-dev

RUN mkdir /etc/supervisor.d \
	&& cp /usr/local/V2RayPi/script/docker/v2ray.ini /etc/supervisor.d/v2ray.ini

EXPOSE 1080
EXPOSE 1086

CMD supervisord -c /etc/supervisord.conf && sh /usr/local/V2RayPi/script/start.sh run