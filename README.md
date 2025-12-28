# AstrBot 币安插件

AstrBot 币安插件，支持通过公共API查询各种资产价格，以及通过绑定API密钥查询个人账户资产信息。

## 功能特性

- **价格查询**：支持现货、合约、杠杆和Alpha货币的价格查询
- **API绑定**：每个用户可以绑定自己的币安API密钥，加密存储
- **资产查询**：绑定API后可以查询账户资产，包括总览、alpha、资金、现货和合约
- **API解绑**：支持解除绑定已绑定的API密钥
- **价格监控**：设置价格监控，当价格达到指定条件时发送通知
- **K线图查询**：支持查询现货、合约、杠杆和Alpha货币的K线数据，可选择不同时间间隔
- **帮助信息**：提供详细的命令使用说明

## 安装方法

将插件文件夹 `astrbot_plugin_binance` 放入 AstrBot 的插件目录即可。

## 命令使用说明

### 1. 价格查询命令

```
/price <交易对> [资产类型]
```

**参数说明**：
- `交易对`：要查询的交易对，例如 BTCUSDT
- `资产类型`：可选，支持的类型包括：
  - spot：现货（默认）
  - futures：合约
  - margin：杠杆
  - alpha：Alpha货币

**示例**：
```
/price BTCUSDT
/price BTCUSDT futures
/price ETHUSDT margin
/price BNBUSDT alpha
```

### 2. API密钥绑定命令

```
/绑定 <API_KEY> <SECRET_KEY>
```

**参数说明**：
- `API_KEY`：您的币安API Key
- `SECRET_KEY`：您的币安API Secret Key

**示例**：
```
/绑定 abcdef123456abcdef123456abcdef123456abcdef abcdef123456abcdef123456abcdef123456abcdef
```

### 3. API密钥解除绑定命令

```
/解除绑定
```

**示例**：
```
/解除绑定
```

### 4. 资产查询命令

```
/资产 [查询类型]
```

**参数说明**：
- `查询类型`：可选，支持的类型包括：
  - alpha：查询Alpha资产
  - 资金：查询资金账户资产
  - 现货：查询现货账户资产
  - 合约：查询合约账户资产
  - 不输入则查询总览

**示例**：
```
/资产
/资产 alpha
/资产 资金
/资产 现货
/资产 合约
```

### 5. 价格监控命令

```
/监控 设置 <交易对> <资产类型> <目标价格> <方向>
/监控 取消 <监控ID>
/监控 列表
```

**参数说明**：
- `交易对`：要监控的交易对，例如 BTCUSDT
- `资产类型`：支持的类型包括：
  - spot：现货
  - futures：合约
  - margin：杠杆
  - alpha：Alpha货币
- `目标价格`：要监控的目标价格
- `方向`：监控方向，支持：
  - up：上涨到目标价格
  - down：下跌到目标价格
- `监控ID`：要取消的监控的ID，可通过监控列表查看

**示例**：
```
/监控 设置 BTCUSDT futures 50000 up
/监控 取消 1
/监控 列表
```

### 6. K线图查询命令

```
/kline <交易对> [资产类型] [时间间隔]
```

**参数说明**：
- `交易对`：要查询的交易对，例如 BTCUSDT
- `资产类型`：可选，支持的类型包括：
  - spot：现货（默认）
  - futures：合约
  - margin：杠杆
  - alpha：Alpha货币
- `时间间隔`：可选，支持的间隔包括：
  - 1m：1分钟
  - 5m：5分钟
  - 15m：15分钟
  - 30m：30分钟
  - 1h：1小时（默认）
  - 4h：4小时
  - 1d：1天

**示例**：
```
/kline BTCUSDT
/kline BTCUSDT futures 1h
/kline ETHUSDT spot 5m
/kline BNBUSDT alpha 4h
```

### 7. 帮助命令

```
/bahelp
```

**示例**：
```
/bahelp
```

## 配置说明

插件配置文件为 `_conf_schema.json`，可以在 AstrBot 管理界面中修改以下配置：

- `api_timeout`：API请求超时时间（秒）
- `api_url`：币安API基础URL
- `api_futures_url`：币安合约API基础URL
- `api_margin_url`：币安杠杆API基础URL
- `api_alpha_url`：币安Alpha API基础URL

## 安全说明

- 用户的API密钥使用AES-CBC加密算法进行加密存储，确保安全
- 建议在绑定API密钥时，仅给予必要的权限（如查询资产权限）
- 请勿将API密钥分享给他人

## 许可证信息

本插件遵循 AGPL 3.0 许可证。
