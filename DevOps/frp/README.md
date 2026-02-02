在一台没有公网IP的服务器（比如内网服务器）上部署了服务，需要将服务暴露到公网，可以frp来做内网穿透，将服务映射到具有公网IP的服务器上

frp 采用 C/S 模式，一般是在具有公网IP的服务器上安装服务端frps，在内网服务器上安装客户端frpc

具体使用场景可以灵活一些，不一定需要是暴露到公网，也可以作为代理来使用

![](https://cdn.jsdelivr.net/gh/r4ining/image-room/blog-article-image/0017/frp-proxy.png)

## Frp 安装与配置

### 安装

Frp 支持 Linux/MacOS/Windows，使用Go语言编写，在Linux上安装只需要将二进制文件放到服务器的`/usr/local/bin`目录即可

项目地址为：https://github.com/fatedier/frp，在 [release](https://github.com/fatedier/frp/releases) 页面下载安装包执行下面步骤安装

安装包中包含了 frps/frpc 二进制文件和对应的配置文件 frps.toml/frpc.toml

```Bash
# 这里的版本仅做示意，可以下载最新版
tar xvf frp_0.66.0_linux_amd64.tar.gz

cd frp_0.65.0_linux_amd64

# 这里可以根据角色仅复制 frps 或 frpc，比如在服务端仅需要 frps 即可，在客户端仅需要 frpc 即可
cp frps frpc /usr/local/bin
```

### frps

#### frps 配置文件

准备 frps 的配置文件

```Bash
mkdir -p /etc/frp
cp frps.toml /etc/frp
```

`frps.toml`文件中默认仅一行配置

```TOML
bindPort = 7000 # frpc 连接 frps 使用的端口
```

可以根据需要添加其他的配置

```TOML
bindPort = 7000
# 
vHostHttpPort = 8000
vhostHTTPSPort = 8443

# frpc 与 frps 身份验证相关配置
auth.method = "token"
auth.token = "gKorkxNogJGolpNL6D3F9OmjPhm"

# Web 页面相关配置
## 默认为 127.0.0.1，如果需要公网访问，需要修改为 0.0.0.0。
webServer.addr = "0.0.0.0"
webServer.port = 7500
## dashboard 用户名密码，可选，默认为空
webServer.user = "admin"
webServer.password = "admin"
## TLS 证书
webServer.tls.certFile = "server.crt"
webServer.tls.keyFile = "server.key"
```

#### frps systemd 配置

通过 systemd 来管理 frps 服务，创建使用的 systemd service 配置文件

```Bash
vim /etc/systemd/system/frps.service
```

内容如下

```TOML
[Unit]
# 服务名称，可自定义
Description = frp server
After = network.target syslog.target
Wants = network.target

[Service]
Type = simple
# 启动frps的命令，需修改为您的frps的安装路径
ExecStart = /usr/local/bin/frps -c /etc/frp/frps.toml

[Install]
WantedBy = multi-user.target
```

使用

```Bash
# 启动frp
sudo systemctl start frps
# 停止frp
sudo systemctl stop frps
# 重启frp
sudo systemctl restart frps
# 查看frp状态
sudo systemctl status frps

# 设置开机自启
sudo systemctl enable frps
```

### frpc

#### frpc 配置文件

准备 frpc 的配置文件

```Bash
mkdir -p /etc/frp
cp frpc.toml /etc/frp
```

`frpc.toml`文件默认中提供了一个代理 ssh 服务的示例

- `serverAddr`和`serverPort`为 frpc 客户端连接的 frps 服务端的地址和端口
- `localIP` 和 `localPort` 配置为需要从公网访问的内网服务的地址和端口
- `remotePort` 表示在 frps 服务端监听的端口，访问此端口的流量将被转发到本地服务的相应端口

```TOML
serverAddr = "127.0.0.1"
serverPort = 7000

[[proxies]]
name = "test-tcp"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = 6000
```

可以根据需要对`frpc.toml`文件进行修改

```TOML
serverAddr = "127.0.0.1"
serverPort = 7000

# 与服务端身份验证配置，需要与服务端的 auth.token 一致
auth.token = "gKorkxNogJGolpNL6D3F9OmjPhm"

[[proxies]]
name = "test-tcp"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = 6000
```
#### frpc systemd 配置

通过 systemd 来管理 frpc 服务，创建使用的 systemd service 配置文件

```Bash
vim /etc/systemd/system/frpc.service
```

内容如下

```TOML
[Unit]
# 服务名称，可自定义
Description = frp client
After = network.target syslog.target
Wants = network.target

[Service]
Type = simple
# 启动frpc的命令，需修改为您的frpc的安装路径
ExecStart = /usr/local/bin/frpc -c /etc/frp/frpc.toml

[Install]
WantedBy = multi-user.target
```

使用

```Bash
# 启动frp
sudo systemctl start frpc
# 停止frp
sudo systemctl stop frpc
# 重启frp
sudo systemctl restart frpc
# 查看frp状态
sudo systemctl status frpc

# 设置开机自启
sudo systemctl enable frpc
```

## 场景

具体的使用场景示例，更多场景可参考 frp 文档：

- https://gofrp.org/zh-cn/docs/examples/
- https://gofrp.org/zh-cn/docs/features/

### 场景一：暴露内网服务（端口）

将内网的某个端口暴露到公网

#### frps 配置

```TOML
bindPort = 7000

auth.method = "token"
auth.token = "gKorkxNogJGolpNL6D3F9OmjPhm"
```

启动frps：

```Bash
systemctl start frps
```

#### frpc 配置

```TOML
# 填写自己实际的 frps 服务端的IP和端口
serverAddr = "1.2.3.4"
serverPort = 7000

# 与服务端身份验证配置，需要与服务端的 auth.token 一致
auth.token = "gKorkxNogJGolpNL6D3F9OmjPhm"

[[proxies]]
name = "ssh-tcp"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = 6000
```

启动frpc：

```Bash
systemctl start frpc
```

#### 验证

```Bash
# 查看 frps 日志，正常将会看到连接成功日志
journalctl -xefu frps

# frps 服务端查看端口，这里的 6000 是 frpc.toml 文件中 remotePort 指定的端口
ss -tnlp | grep 6000

# 使用 ssh 连接，如果是其他 http 服务，可以直接在浏览器访问
ssh -o Port=6000 root@1.2.3.4
```

### 场景二：暴露内网 HTTP 服务

将内网的 http 服务暴露到公网

#### frps 配置

```TOML
bindPort = 7000
# 指定监听在本地的 vHost 端口
vHostHttpPort = 80
# vhostHTTPSPort = 443

# frpc 与 frps 身份验证相关配置
auth.method = "token"
auth.token = "gKorkxNogJGolpNL6D3F9OmjPhm"
```

启动frps：

```Bash
systemctl start frps
```

#### frpc 配置

代理 Web 服务可以使用 http 类型的代理（配置文件中通过`type`指定）

> frp官网的内容：HTTP 类型的代理非常适合将内网的 Web 服务通过自定义域名提供给外部用户。相比于 TCP 类型代理，HTTP 代理不仅可以复用端口，还提供了基于 HTTP 协议的许多功能。

```TOML
# 填写自己实际的 frps 服务端的IP和端口
serverAddr = "1.2.3.4"
serverPort = 7000

# 与服务端身份验证配置，需要与服务端的 auth.token 一致
auth.token = "gKorkxNogJGolpNL6D3F9OmjPhm"

[[proxies]]
name = "web-a"
type = "http"
localPort = 8080
customDomains = ["a.example.com"]

[[proxies]]
name = "web-b"
type = "http"
localPort = 80
customDomains = ["b.example.com"]
```

启动frpc：

```Bash
systemctl start frpc
```

#### 验证

需要将使用的域名添加解析，随后在在浏览器上访问`http://``a.example.com`和`http://b.example.com`

如果无法访问，可以为 frps 开启 web 界面，在界面上可以查看各种类型代理的配置

### 场景三：暴露内网 HTTP 服务（公网服务器上vHost非80）

这是在场景二的基础上，frps 服务端的 80 端口已经被使用，无法指定`vHostHttpPort`为 80 端口，在这个基础上添加 nginx 转发，主要是记录下 nginx 的配置

#### frps 配置

配置中只有`vHostHttpPort`不同

```TOML
bindPort = 7000
# 指定监听在本地的 vHost 端口
vHostHttpPort = 8080
# vhostHTTPSPort = 443

# frpc 与 frps 身份验证相关配置
auth.method = "token"
auth.token = "gKorkxNogJGolpNL6D3F9OmjPhm"
```

启动frps：

```Bash
systemctl start frps

# 会监听 8080 端口
ss -tnlp | grep 8080
```

#### frpc 配置

代理 Web 服务可以使用 http 类型的代理（配置文件中通过`type`指定）

> frp官网的内容：HTTP 类型的代理非常适合将内网的 Web 服务通过自定义域名提供给外部用户。相比于 TCP 类型代理，HTTP 代理不仅可以复用端口，还提供了基于 HTTP 协议的许多功能。

```TOML
# 填写自己实际的 frps 服务端的IP和端口
serverAddr = "1.2.3.4"
serverPort = 7000

# 与服务端身份验证配置，需要与服务端的 auth.token 一致
auth.token = "gKorkxNogJGolpNL6D3F9OmjPhm"

[[proxies]]
name = "web-a"
type = "http"
localPort = 8080
customDomains = ["a.example.com"]

[[proxies]]
name = "web-b"
type = "http"
localPort = 80
customDomains = ["b.example.com"]
```

启动frpc：

```Bash
systemctl start frpc
```

#### Nginx 配置

使用 nginx 做代理转发

```Nginx
# /etc/nginx/conf.d/example.com.conf
server {
    #listen 80;
    listen 443 ssl;
    server_name a.example.com;
    client_max_body_size 100m;

    # SSL 证书
    ssl_certificate     /etc/nginx/cert/a.example.com.crt;
    ssl_certificate_key /etc/nginx/cert/a.example.com.key;

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_pass http://127.0.0.1:8080;
    }
}

server {
    #listen 80;
    listen 443 ssl;
    server_name b.example.com;
    client_max_body_size 100m;

    # SSL 证书
    ssl_certificate     /etc/nginx/cert/b.example.com.crt;
    ssl_certificate_key /etc/nginx/cert/b.example.com.key;

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_pass http://127.0.0.1:8080;
    }
}
```

重载nginx

```Bash
systemctl restart nginx

或者 
nginx -s reload
```
